"""Intent → execute → reconcile.

GitHub and FalkorDB are two systems; no transaction spans both. Every approved action first writes an
`(:Intent {idem, state:'PENDING'})` in the same query as its Approval. If the process dies, or verification
cannot read GitHub (S9), the intent stays PENDING. The reconciler runs at API start and before each execute.
For every PENDING intent older than `older_than_ms`, it asks the external system by the idempotency key:

* our `faultline/fix-<idem8>` PR is merged AND main carries the change (issue: found by its idem key; data repair:
  the transform on disk carries the patch):
  re-verify through BOTH channels (`act.verify`, 3-valued) and write back from that verdict;
* the change is not at main HEAD: the action did not happen. NOT_APPLIED, the intent becomes FAILED, and a
  human must re-approve (we never silently re-execute an old approval);
* GitHub cannot be read: UNKNOWN with an explanation, the intent stays PENDING, and the run is escalated.

Each step is its own single-query write (writes.py); the reconciler only reads through templates.

Leases (review round 4, M5): an execute job in flight holds its intent's lease (set at approval, renewed before every
step), and Q-INTENT-1 skips leased intents. The reconciler claims each intent atomically (W-INTENT-CLAIM: only an
unleased or expired one) before it touches it, and every verdict, write-back and stage write it makes is conditional
on the intent still being PENDING and leased to it, in the same query. Whichever writer settles the intent first wins;
the other one's writes match nothing (IntentNotPending) and it stops without moving the stage.

Round 5 (M1, minors 1, 8): every time comparison runs on the engine clock (Q-INTENT-1 and W-INTENT-CLAIM use
timestamp(); no caller-supplied `now`). A lease names the process boot that holds it (boot.py): a lease whose boot
stopped heartbeating is taken over at once, an expired one as before. The API runs this periodically (api.py), so a
crashed execute job's intent is settled within about a minute of its process dying, not only at the next approval. A
simulated GitHub that lives in process memory was reset by a restart: an intent approved by an earlier process is
UNKNOWN there (escalated), never "absent". A data repair is reconciled under the warehouse's exclusive hold. A repeated
UNKNOWN (same explanation, already escalated) writes nothing new.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from ..agent.state import Stage, ordinal
from ..graph import writes
from ..graph.ro import RO
from . import act
from . import boot
from . import github as gh

log = logging.getLogger("faultline.reconcile")

# world(incident_id) → kwargs for act.verify's second channel {symptom, onset_ms, effects, at_ms}, or None
World = Callable[[str], dict | None]


@dataclass
class Outcome:
    incident: str
    action: str
    idem: str
    found: str          # "at_main" | "absent" | "unreadable" | "issue"
    verdict: str        # APPLIED | NOT_APPLIED | UNKNOWN
    explanation: str
    writeback: str | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _found(spec: dict, kind: str, hub: gh.GitHub) -> str:
    """Ask the external system by the idempotency key. → 'at_main' | 'absent' (GitHubError propagates)."""
    if kind == "open_issue":
        return "at_main" if hub.find_issue(spec["args"]["repo"], f"Faultline-Idem: {spec['idem']}") else "absent"
    if kind == "data_repair":
        from .. import repair

        return "at_main" if repair._resolve_transform(spec["file"]).read_text() == spec["after"] else "absent"
    # attribution: OUR fix PR (faultline/fix-<idem8>) must be merged AND main must carry the change; an out-of-band
    # change with the same effect is not this intent's execution
    pr = hub.find_pr(spec["args"]["repo"], spec["branch"])
    if not pr or pr.get("state") != "merged":
        return "absent"
    main, _ = hub.get_file(spec["args"]["repo"], spec["file"], "main")
    doc = json.loads(main)
    if kind == "flip_flag":
        ok = doc["flags"][spec["args"]["flag"]]["state"] == spec["args"]["state"]
    else:
        ok = doc.get("deploys", {}).get(spec["args"]["service"], {}).get("reverted") == spec["args"]["revert"]
    return "at_main" if ok else "absent"


def _escalate(c: act.Ctx, aid: str, note: str) -> None:
    writes.advance_stage(c.g(), inc=c.inc, run=c.run, stage=Stage.UNKNOWN_ESCALATED.value,
                         ord_=ordinal(Stage.UNKNOWN_ESCALATED), note=note[:400], force=True, aid=aid, owner=c.owner,
                         settled=True)


def _stage(c: act.Ctx, aid: str, stage: Stage, note: str) -> None:
    writes.advance_stage(c.g(), inc=c.inc, run=c.run, stage=stage.value, ord_=ordinal(stage), note=note, force=True,
                         aid=aid, owner=c.owner, settled=True)


def _grace_ms() -> int:
    from ..agent.weights import weights

    return int(weights()["actions"]["reconcile_grace_s"]) * 1000


def _repeat(it: dict, verdict: str, why: str) -> bool:
    """This UNKNOWN was already recorded and escalated (a periodic reconcile must not add a stage event a minute)."""
    return verdict == "UNKNOWN" and it.get("verdict") == "UNKNOWN" and it.get("explanation") == why \
        and it.get("stage") == Stage.UNKNOWN_ESCALATED.value


def _unknown(c: act.Ctx, it: dict, aid: str, found: str, why: str, channels: dict) -> Outcome:
    o = Outcome(c.inc, aid, it["idem"], found, "UNKNOWN", why)
    if _repeat(it, "UNKNOWN", why):
        o.found = f"{found} (unchanged; already escalated)"
        return o
    writes.record_verdict(c.g(), aid=aid, verdict="UNKNOWN", why=why, channels=channels, owner=c.owner)
    writes.write_back_not_applied(c.g(), inc=c.inc, aid=aid, stage=Stage.UNKNOWN_ESCALATED.value, owner=c.owner)
    _escalate(c, aid, f"reconciled ({found}): {why}"[:400])
    return o


def reconcile_one(it: dict, tenant: str, graph: str, hub: gh.GitHub, world: World, owner: str | None = None) -> Outcome:
    """Settle one intent. `owner`: the lease the caller claimed for it (W-INTENT-CLAIM); every write is bound to it."""
    c = act.Ctx(tenant, graph, it["incident"], it["run"], owner)
    spec = json.loads(it["spec"]) if it["spec"] else {}
    aid, kind = it["action"], it["kind"]
    if kind != "data_repair" and gh.ephemeral(hub) and it.get("created_boot") != boot.BOOT_ID:
        why = ("the simulated GitHub world lives in process memory and was reset when the API restarted (this intent "
               "was approved by an earlier process): whether the change happened cannot be told; still PENDING, escalated")
        return _unknown(c, it, aid, "world_reset", why, {"external": {"ok": None, "reason": "simulated world reset"}})
    try:
        found = _found(spec, kind, hub)
    except (gh.GitHubError, OSError, KeyError, ValueError) as e:
        log.warning("reconcile %s: external state unreadable: %s: %s", it["idem"][:12], type(e).__name__, e)
        why = (f"reconciler could not read the external state for idem {it['idem'][:12]} ({type(e).__name__}); "
               "still PENDING, escalated")
        return _unknown(c, it, aid, "unreadable", why, {"external": {"ok": None, "error": type(e).__name__}})
    cause = (c.ro().run("Q-CAUSE-1", {"inc": c.inc}).rows or [{}])[0].get("cause")
    if found == "at_main":
        if not it["external_ref"]:  # executed but never recorded (crash between the external change and the write)
            pr = hub.find_pr(spec["args"]["repo"], spec["branch"]) if kind in ("flip_flag", "rollback_deploy") else None
            writes.record_execution(c.g(), aid=aid, ref=(pr or {}).get("url", f"reconciled:{spec.get('file', kind)}"),
                                    detail={"reconciled": True, "pr": pr, "served_by": hub.label}, owner=c.owner)
        w = {} if kind in ("open_issue", "data_repair") else world(c.inc)
        if w is None:
            why = "the change is at main HEAD, but the second channel (telemetry) is not available for this incident; escalated"
            return _unknown(c, it, aid, found, why, {"github_main": {"ok": True}})
        if kind in ("open_issue", "data_repair"):
            v = act.verify(c, aid, hub, symptom=[], onset_ms=0, effects=[], at_ms=int(time.time() * 1000))
        else:
            v = act.verify(c, aid, hub, **w)
    else:
        v = {"verdict": "NOT_APPLIED",
             "explanation": f"reconciler: the fix PR for idem {it['idem'][:12]} ({spec.get('branch', kind)}) is not merged / "
                            "the change is not there; the approval is void, choose again"}
        writes.record_verdict(c.g(), aid=aid, verdict="NOT_APPLIED", why=v["explanation"], channels={"external": {"ok": False}},
                             owner=c.owner)
    o = Outcome(c.inc, aid, it["idem"], found, v["verdict"], v["explanation"])
    if v["verdict"] == "APPLIED" and kind != "open_issue" and cause:
        wb = act.write_back(c, aid, cause=cause, confident=True)
        o.writeback = wb.get("verified")
        n, m = (int(x) for x in (o.writeback or "0/1").split("/"))
        if n == m:
            _stage(c, aid, Stage.RESOLVED, f"reconciled ({found}); write-back verified {o.writeback}")
        else:
            _escalate(c, aid, f"reconciled ({found}); write-back re-read incomplete ({o.writeback}), escalated")
    elif v["verdict"] == "APPLIED":  # an issue (tracking only), or no confirmed cause to write back
        if kind == "open_issue":
            act.write_back(c, aid, cause=cause or "", confident=True)
        _escalate(c, aid, f"reconciled ({found}): {v['explanation'][:300]}")
    elif v["verdict"] == "NOT_APPLIED":
        writes.write_back_not_applied(c.g(), inc=c.inc, aid=aid, stage=Stage.AWAITING_APPROVAL.value, owner=c.owner)
        _stage(c, aid, Stage.AWAITING_APPROVAL, f"reconciled ({found}): {v['explanation'][:300]}")
    else:
        writes.write_back_not_applied(c.g(), inc=c.inc, aid=aid, stage=Stage.UNKNOWN_ESCALATED.value, owner=c.owner)
        _escalate(c, aid, f"reconciled ({found}): {v['explanation'][:300]}")
    return o


def reconcile(tenant: str, graph: str, hub: gh.GitHub, world: World, *, older_than_ms: int | None = None,
              role: str = "reconciler", warehouse_wait_s: float = 30.0, oncall_home: str | None = None) -> list[dict]:
    """Each intent on its own: one stuck intent never blocks the others (its failure is recorded on its incident).
    `older_than_ms`: the grace for intents that were never leased (direct callers); default weights.yaml
    actions.reconcile_grace_s. Leased intents are taken when their lease expired or their boot is dead (engine clock).
    `oncall_home` (the API passes the tenant graph): an intent settled without a verified, resolved fix pages a human
    (oncall.page_after_approval, idempotent per outcome); None keeps paging off (benches, direct callers)."""
    from ..public_errors import client_text

    grace = _grace_ms() if older_than_ms is None else int(older_than_ms)
    try:
        boot.beat(tenant, role)  # this process is alive: its own claims must not look like a dead boot's
    except Exception as e:  # noqa: BLE001 - liveness is an optimisation; expiry still applies
        log.warning("boot heartbeat for %s failed: %s", tenant, e)
    live = boot.live(tenant)
    out: list[dict] = []
    here = gh.world_id()
    for it in RO(tenant, graph).run("Q-INTENT-1", {"grace_ms": grace, "live": live}).rows:
        w = it.get("world")
        if w and w.startswith("dir:") and w != here:
            continue  # acted in a persisted world this process cannot see: left for a reconciler that shares it
        owner = f"{boot.BOOT_ID}:reconcile-{uuid.uuid4().hex[:12]}"
        g = act.Ctx(tenant, graph, it["incident"], it["run"]).g()
        if not writes.claim_intent(g, idem=it["idem"], owner=owner, lease_ms=act.lease_ms(), boot=boot.BOOT_ID, live=live,
                                   grace_ms=grace):
            continue  # leased by a live execute job (or another reconciler) since the read: theirs to settle
        c = act.Ctx(tenant, graph, it["incident"], it["run"], owner)
        try:
            if it["kind"] == "data_repair":  # the warehouse alone: no run reads it while the repair is re-verified
                from ..scenario import WAREHOUSE, WarehouseBusy

                try:
                    with WAREHOUSE.exclusive(timeout=warehouse_wait_s, heartbeat=lambda: act.renew(c, it["action"])):
                        out.append(reconcile_one(it, tenant, graph, hub, world, owner).as_dict())
                except WarehouseBusy as e:  # runs hold the warehouse: try again at the next reconcile, write nothing
                    out.append({"incident": it["incident"], "action": it["action"], "idem": it["idem"],
                                "found": "warehouse_busy", "verdict": None, "explanation": str(e)[:300], "writeback": None})
            else:
                out.append(reconcile_one(it, tenant, graph, hub, world, owner).as_dict())
        except writes.IntentNotPending as e:  # settled elsewhere meanwhile: theirs stands, nothing more is written
            out.append({"incident": it["incident"], "action": it["action"], "idem": it["idem"], "found": "settled_elsewhere",
                        "verdict": None, "explanation": str(e)[:300], "writeback": None})
        except Exception as e:  # noqa: BLE001 - recorded on the incident, never raised to the caller
            text = client_text(e)
            try:
                _escalate(c, it["action"], f"reconciler error on {it['action']}: {text}")
            except Exception:  # noqa: BLE001
                pass
            out.append({"incident": it["incident"], "action": it["action"], "idem": it["idem"], "found": "error",
                        "verdict": "UNKNOWN", "explanation": text[:300], "writeback": None})
        finally:  # an intent left PENDING (UNKNOWN) is open to the next reconcile at once, as before leases
            try:
                writes.release_intent(g, aid=it["action"], owner=owner)
            except Exception:  # noqa: BLE001 - the lease then simply expires
                pass
        if oncall_home is not None and out and out[-1].get("verdict") is not None:
            try:
                from . import oncall

                oncall.page_after_approval(tenant, graph, it["incident"], it["run"], it["action"])
            except Exception as e:  # noqa: BLE001 - the stage still says it; logged loudly
                log.error("paging after reconciling %s/%s failed: %s", it["incident"], it["action"], e)
    return out


__all__ = ["reconcile", "reconcile_one", "Outcome"]
