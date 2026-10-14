"""Generic scenario runner. Scenario definitions are config (data/scenarios/scenarios.yaml); ground
truth is NEVER read here (grader-only). Each run gets a fresh GRAPH.COPY clean room of golden_<t>.

prepare: copy golden → eval_<t>_<tag>, inject changes, raise alerts, set the warehouse fixture mode
run:     intake (symptoms = alerts that fired at onset) → agent v2 loop → result
"""

from __future__ import annotations

import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import REPO_ROOT
from .graph import client as gclient
from .graph import copy as gcopy
from .graph import writes
from .graph.ro import RO
from .graph.tenant import eval_graph, golden_graph, graph_belongs_to
from .agent.intake import intake_round
from .agent.weights import weights
from .ingest.clock import ANCHOR_MS

SCENARIOS = REPO_ROOT / "data" / "scenarios" / "scenarios.yaml"
_REL = re.compile(r"^(anchor)?\s*([+-])?\s*(\d+)\s*([smhd])$")
_UNIT = {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def rel_ms(expr: str | int, base: int) -> int:
    """'anchor+2h' → ANCHOR+2h; '-10m' → base−10m; '0m' → base; ints are absolute epoch ms."""
    if isinstance(expr, int):
        return expr
    m = _REL.match(str(expr).replace(" ", ""))
    if not m:
        raise ValueError(f"bad relative time {expr!r}")
    anchor, sign, n, unit = m.groups()
    origin = ANCHOR_MS if anchor else base
    delta = int(n) * _UNIT[unit]
    return origin - delta if sign == "-" else origin + delta


def scenario_onset(s: dict) -> int:
    """The scenario's onset (config, relative to the clock anchor): every effect and alert time is relative to it."""
    return rel_ms(s["onset"], ANCHOR_MS)


def load(sid: str) -> dict:
    for s in yaml.safe_load(SCENARIOS.read_text()):
        if s["id"] == sid:
            return s
    raise KeyError(f"unknown scenario {sid}")


@dataclass
class Prepared:
    """The first incident INTAKE opened (incident_id / run_id / symptoms, unchanged for single-group scenarios) and
    every incident group of the round (`groups`, first = the same incident)."""
    scenario: dict
    tenant: str
    graph: str
    onset_ms: int
    incident_id: str
    run_id: str
    symptoms: list[str]
    groups: list = field(default_factory=list)       # agent.intake.Opened, one per incident opened at onset
    intake: list = field(default_factory=list)       # agent.intake.Round per intake round (onset, then late rounds)


def effects_of(s: dict, onset: int) -> list:
    """The scenario's simulated world effects (config), relative to onset."""
    from .sim.telemetry import Effect

    return [Effect(e["target"], float(e["error_rate"]), rel_ms(e["from"], onset),
                   rel_ms(e["until"], onset) if e.get("until") else None, e.get("change")) for e in s.get("effects", [])]


def set_pipeline_mode(mode: str, *, restore_transforms: bool = True, rebuild: bool = True) -> None:
    """Switch the existing data fixture (system under observation) and rebuild the warehouse.

    `restore_transforms` (review round 5, M3): every mode switch first puts the transforms back to their pristine,
    hash-checked copies (pipeline/transforms_pristine), so an approved repair never outlives the run that made it. A
    data repair re-establishes its incident's fixture with `restore_transforms=False` (its own patch must stay) and
    `rebuild=False` when it rebuilds itself. The subprocesses get a scrubbed environment (no API secrets) and their
    stderr goes to the log, never into a client-visible message."""
    from . import repair, warehouse

    if mode not in ("healthy", "incident"):
        raise ValueError(f"unknown fixture mode {mode!r}")
    if restore_transforms:
        repair.restore_pristine()
    steps = [[sys.executable, "pipeline/generate_sources.py", "--mode", mode]]
    if rebuild:
        steps.append([sys.executable, "pipeline/run.py"])
    for cmd in steps:
        warehouse.run_step(cmd, what=f"pipeline step {Path(cmd[1]).name}", timeout=600)


class WarehouseBusy(RuntimeError):
    """The warehouse is held in another fixture mode by a run that reads it (or a data repair holds it alone)."""


class _Generation:
    def __init__(self, claimable: bool = False) -> None:
        self.built = threading.Event()
        self.error: BaseException | None = None
        self.handoff: "_Generation | None" = None   # the builder left without building: the next generation to build
        self.claimable = claimable                   # nobody has taken this generation's build yet


class Lease:
    """A run's hold on the warehouse in one fixture mode, from before prepare to the end of its investigation. The
    first holder of a mode builds it (`ready`); later holders of the same mode share the build and wait for it. If the
    builder releases without building, the build passes to a remaining holder (never an error left to the joiners)."""

    def __init__(self, gate: "ModeGate", mode: str, gen: _Generation, builder: bool):
        self.gate, self.mode, self._gen, self._builder, self._released = gate, mode, gen, builder, False

    def ready(self, timeout: float = 900.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if self._builder:
                gen = self._gen
                try:
                    self.gate._build(self.mode)
                except BaseException as e:
                    gen.error = e
                    raise
                finally:
                    self._builder = False
                    gen.built.set()
                return
            gen = self._gen
            if not gen.built.wait(max(0.0, deadline - time.monotonic())):
                raise WarehouseBusy(f"the warehouse build for mode {self.mode!r} did not finish within {timeout:.0f} s")
            if gen.handoff is not None:  # the builder stopped before building: take the build over, or wait for it
                with self.gate._cv:
                    nxt = gen.handoff
                    while nxt.handoff is not None:
                        nxt = nxt.handoff
                    self._gen = nxt
                    if nxt.claimable:
                        nxt.claimable = False
                        self._builder = True
                continue
            if gen.error is not None:
                raise WarehouseBusy(f"the warehouse build for mode {self.mode!r} failed: {gen.error}")
            return

    def release(self) -> None:
        if not self._released:
            self._released = True
            self.gate._release(self)


class ModeGate:
    """Review round 4, M4 (round 5: fairness, a cross-process file lock, a re-entrant exclusive hold): there is ONE
    DuckDB warehouse (the system under observation) and a data scenario rebuilds it in its own fixture mode
    (set_pipeline_mode).

    Scope. The gate's bookkeeping is per PROCESS (threads of one API, one eval harness, one CLI). Across processes,
    `lock_path` adds an fcntl file lock next to the DuckDB file: a process takes it when its gate goes from idle to
    busy and drops it when the gate is idle again, so `make eval`, the CLI and the API never use the warehouse at the
    same time (one process at a time; inside it, same-mode runs still share one build).

    Rules. Runs needing the same mode share it; a different mode waits until every run holding the current one has
    released it (or, `wait=False`, is refused with WarehouseBusy); a data repair (`exclusive`) has it alone. Waiters
    are served first come, first served: a waiting different mode or a waiting repair blocks later joiners of the
    current mode, so neither can starve. The first holder after the warehouse was idle rebuilds it (a repair may have
    patched a transform since; every build restores the pristine transforms first)."""

    def __init__(self, build, lock_path: Path | None = None) -> None:
        self._build = build
        self._cv = threading.Condition()
        self.mode: str | None = None
        self.users = 0
        self.alone = False
        self._alone_owner: int | None = None
        self._alone_depth = 0
        self._gen: _Generation | None = None
        self._queue: list[object] = []
        self._lock_path = lock_path
        self._lock_fd: int | None = None

    # -- the cross-process file lock (caller holds _cv) --------------------------------------------------------------
    def _try_file_lock(self) -> bool:
        if self._lock_path is None or self._lock_fd is not None:
            return True
        import fcntl
        import os

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def _drop_file_lock_if_idle(self) -> None:
        if self._lock_fd is not None and self.users == 0 and not self.alone:
            import fcntl
            import os

            fd, self._lock_fd = self._lock_fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _wait_turn(self, ticket: object, can_enter, why, *, wait: bool, deadline: float, heartbeat=None) -> None:
        """Queue `ticket` and wait (caller holds _cv) until it is first in line, `can_enter()` and the file lock is
        ours. `heartbeat` (an execute job renewing its intent lease) runs about every 30 s while waiting, outside _cv."""
        self._queue.append(ticket)
        beat_at = time.monotonic() + 30.0
        try:
            while True:
                first = self._queue[0] is ticket
                if first and can_enter():
                    if self._try_file_lock():
                        self._queue.remove(ticket)
                        self._cv.notify_all()  # the next in line may share this mode
                        return
                    reason = "another process (make eval, the CLI or another API) is using the warehouse"
                else:
                    reason = why()
                if not wait:
                    raise WarehouseBusy(reason)
                left = deadline - time.monotonic()
                if left <= 0:
                    raise WarehouseBusy(f"{reason}; waited for the warehouse until the timeout")
                self._cv.wait(min(left, 0.25 if first else 5.0))
                if heartbeat is not None and time.monotonic() >= beat_at:
                    self._cv.release()
                    try:
                        heartbeat()
                    finally:
                        self._cv.acquire()
                    beat_at = time.monotonic() + 30.0
        except BaseException:
            if ticket in self._queue:
                self._queue.remove(ticket)
            self._cv.notify_all()
            raise

    def reserve(self, mode: str, *, wait: bool = True, timeout: float = 900.0) -> Lease:
        deadline = time.monotonic() + timeout

        def can_enter() -> bool:
            return not self.alone and (self.users == 0 or self.mode == mode)

        def why() -> str:
            if self.alone:
                w = "a data repair is rebuilding the warehouse"
            elif self.users and self.mode != mode:
                w = f"the warehouse is in mode {self.mode!r} for {self.users} active run(s)"
            else:
                w = "other runs are waiting for the warehouse first"
            return f"{w}; this scenario needs mode {mode!r}: try again when it finishes"

        with self._cv:
            self._wait_turn(object(), can_enter, why, wait=wait, deadline=deadline)
            if self.users == 0 or self._gen is None:
                self._gen = _Generation()
                builder = True
            elif self._gen.claimable:
                self._gen.claimable = False
                builder = True
            else:
                builder = False
            self.users += 1
            self.mode = mode
            return Lease(self, mode, self._gen, builder)

    def _release(self, lease: Lease) -> None:
        with self._cv:
            self.users -= 1
            if lease._builder:  # reserved but never built: hand the build to a remaining holder (no error for them)
                lease._builder = False
                gen = lease._gen
                if self.users > 0 and self._gen is gen:
                    nxt = _Generation(claimable=True)
                    gen.handoff = nxt
                    self._gen = nxt
                gen.built.set()
            if self.users == 0:
                self._gen = None
            self._drop_file_lock_if_idle()
            self._cv.notify_all()

    @contextmanager
    def use(self, mode: str, *, wait: bool = True):
        lease = self.reserve(mode, wait=wait)
        try:
            lease.ready()
            yield lease
        finally:
            lease.release()

    @contextmanager
    def exclusive(self, timeout: float = 900.0, heartbeat=None):
        """The warehouse alone (a data repair patches a transform and rebuilds): waits for every run to release it.
        Re-entrant for the thread that holds it (an execute job holds it across execute + verify, and both take it)."""
        me = threading.get_ident()
        with self._cv:
            if self.alone and self._alone_owner == me:
                self._alone_depth += 1
                nested = True
            else:
                nested = False
                self._wait_turn(object(), lambda: not self.alone and self.users == 0,
                                lambda: (f"{self.users} run(s) hold the warehouse" if self.users else
                                         "another data repair holds the warehouse"),
                                wait=timeout > 0, deadline=time.monotonic() + max(timeout, 0.0), heartbeat=heartbeat)
                self.alone, self._alone_owner, self._alone_depth = True, me, 1
        try:
            yield
        finally:
            with self._cv:
                if nested:
                    self._alone_depth -= 1
                else:
                    self.alone, self._alone_owner, self._alone_depth, self.mode = False, None, 0, None
                    self._gen = None
                    self._drop_file_lock_if_idle()
                    self._cv.notify_all()

    def held_alone_by_me(self) -> bool:
        with self._cv:
            return self.alone and self._alone_owner == threading.get_ident()


def _warehouse_lock_path() -> Path:
    from .config import settings

    return settings.warehouse_path.with_name(settings.warehouse_path.name + ".lock")


def restore_warehouse(timeout: float = 5.0) -> dict:
    """Re-arm (review round 5, M3): put the transforms back to pristine and rebuild if any had changed, under the
    warehouse's exclusive hold. If runs hold the warehouse now, nothing is touched: every run's mode switch restores
    the pristine transforms before it builds anyway."""
    from . import repair, warehouse

    try:
        with WAREHOUSE.exclusive(timeout=timeout):
            restored = repair.restore_pristine()
            if restored:
                b = warehouse.rebuild_warehouse()
                return {"restored": restored, "rebuilt": bool(b["ok"])}
            return {"restored": [], "rebuilt": False}
    except WarehouseBusy:
        return {"restored": None, "note": "warehouse in use; transforms are restored when the next run sets its mode"}


WAREHOUSE = ModeGate(lambda mode: set_pipeline_mode(mode), lock_path=_warehouse_lock_path())


def prepare(sid: str, tag: str | None = None, set_mode: bool = True, graph: str | None = None,
            nomem: bool = False, spec: dict | None = None, lease: Lease | None = None, origin: str = "cli") -> Prepared:
    """Copy golden → a fresh eval graph and inject the scenario. With `graph`, inject into that EXISTING graph
    instead (warm memory: the next incident in the same graph after an earlier one was resolved). `spec`: a
    scenario definition in the scenarios.yaml shape that is not in the file (generated eval cases, e.g.
    evals/gate_bench.py); same intake path, still no ground truth. `lease`: the caller's hold on the warehouse in this
    scenario's fixture mode (WAREHOUSE.reserve), kept until its investigation ends; without one, the mode is set under
    a hold that lasts only for the build (callers that read the warehouse afterwards should pass a lease). `origin`
    names who made the clean room (`eval_<t>_<origin>_v2_…`): the API's collector only ever deletes its own ("api")."""
    s = spec if spec is not None else load(sid)
    tenant = s["tenant"]
    tag = tag or uuid.uuid4().hex[:8]
    db = gclient.engine()
    if graph is None:
        graph = eval_graph(tenant, origin, "v2", sid.lower(), int(tag, 16) % 10_000 if re.fullmatch(r"[0-9a-f]+", tag) else 0)
        graph = f"{graph}_{tag}" if not graph.endswith(tag) else graph
        gcopy.delete_if_exists(db, graph)
        gcopy.copy_graph(db, golden_graph(tenant, nomem=nomem), graph)  # nomem: memory-off eval arm (A2)
    elif not graph_belongs_to(graph, tenant) or not gcopy.exists(db, graph):
        raise ValueError(f"{sid}: warm graph {graph!r} does not exist or does not belong to {tenant!r}")
    g = db.select_graph(graph)
    onset = scenario_onset(s)
    for c in s.get("inject", []):
        writes.inject_change(g, id=c["change"], target=c["target"], at=rel_ms(c["at"], onset), kind=c.get("kind", "deploy"),
                             title=c.get("title", ""), tenant=tenant)
    for a in s.get("alerts", []):
        writes.raise_alert(g, id=a["id"], target=a["target"], metric=a["metric"], at=rel_ms(a["at"], onset))
    for flag, state in (s.get("world_flags") or {}).items():  # out-of-band flag changes since the last incident
        from .actions import act
        from .actions import github as gh

        act.set_world_flag(act.Ctx(tenant, graph, "", ""), gh.client(graph), flag, state, why=f"scenario {sid}: world change")
    for f in s.get("facts", []):
        writes.assert_change_fact(g, change=f["change"], key=f["key"], value=f["value"], about=f["about"], file=f.get("file", ""))
    if s.get("effects") or not s.get("pipeline_mode"):  # service scenarios always get telemetry (healthy if no effects)
        from .sim.telemetry import simulate

        effects = effects_of(s, onset)
        simulate(g, RO(tenant, graph), onset_ms=onset, effects=effects, seed=int(s.get("seed", 42)),
                 base_seed=int(s.get("seed", 42)), noise=float(s.get("noise", 0.15)))
    if set_mode and s.get("pipeline_mode"):
        if lease is not None:
            if lease.mode != s["pipeline_mode"]:
                raise ValueError(f"{sid} needs warehouse mode {s['pipeline_mode']!r}, the lease holds {lease.mode!r}")
            lease.ready()
        else:
            with WAREHOUSE.use(s["pipeline_mode"]):
                pass
    # INTAKE: the symptom alerts that fired around onset, grouped into independent incidents by the graph (group_alerts:
    # algo.WCC over the failure-carrying alert projection); one incident per group, its symptoms = the group's targets
    w = weights()["intake"]
    base_inc, base_run = f"inc-{sid.lower()}-{tag}", f"run-{sid.lower()}-{tag}"
    ids = [(base_inc, base_run)] + [(f"{base_inc}-{k}", f"{base_run}-{k}") for k in range(2, 21)]
    rnd = intake_round(tenant=tenant, graph=graph, since=onset - int(w["alert_lead_min"]) * 60_000,
                       until=onset + int(w["alert_lag_min"]) * 60_000, onset=onset, ids=ids, title=s.get("name", sid),
                       report=s.get("report", ""), round_run=f"{base_run}-intake",
                       embed=lambda g_, inc, alerts: embed_incident(g_, inc, s.get("report") or s.get("name", sid),
                                                                     symptom_texts(alerts, sorted({a["target"] for a in alerts}))))
    if not rnd.opened:
        raise RuntimeError(f"{sid}: no alert fired around onset that an open incident does not already hold; "
                           f"nothing new to investigate (attached: {rnd.attached})")
    first = rnd.opened[0]
    return Prepared(s, tenant, graph, onset, first.incident_id, first.run_id, first.symptoms, rnd.opened, [rnd])


def late_rounds(p: Prepared) -> list[tuple[int, int]]:
    """The scenario's later intake windows: alerts configured to fire after the onset round's window arrive in one
    more round, (onset round end, last such alert + lag]. Read from the scenario config, never from truth."""
    w = weights()["intake"]
    end = p.onset_ms + int(w["alert_lag_min"]) * 60_000
    late = [rel_ms(a["at"], p.onset_ms) for a in p.scenario.get("alerts", []) if rel_ms(a["at"], p.onset_ms) > end]
    return [(end + 1, max(late) + int(w["alert_lag_min"]) * 60_000)] if late else []


def intake_late(p: Prepared, since: int, until: int, k: int = 2):
    """A later INTAKE round in the same graph: its alerts attach to the open incident whose confirmed origin reaches
    them, or open new incidents, each with its own onset (the first alert of its group, review M6)."""
    s = p.scenario
    base_inc, base_run = p.incident_id, p.run_id
    ids = [(f"{base_inc}-r{k}-{j}", f"{base_run}-r{k}-{j}") for j in range(1, 21)]
    rnd = intake_round(tenant=p.tenant, graph=p.graph, since=since, until=until, onset=None, ids=ids,
                       title=s.get("name", ""), report=s.get("report", ""), round_run=f"{base_run}-intake{k}",
                       embed=lambda g_, inc, alerts: embed_incident(g_, inc, s.get("report") or s.get("name", ""),
                                                                     symptom_texts(alerts, sorted({a["target"] for a in alerts}))))
    p.intake.append(rnd)
    return rnd


def symptom_texts(alerts: list[dict], symptoms: list[str]) -> list[str]:
    """Same shape as the seeded history's symptom text ('error_rate checkout')."""
    return [f"{next(a['metric'] for a in alerts if a['target'] == t)} {t}" for t in symptoms]


def embed_incident(g, inc: str, text: str, symptoms: list[str]) -> None:
    """Embed the incident (local model) and store the vector on its node with vecf32(), so recall and every
    future incident can find it in the FalkorDB vector index."""
    from .memory.embed import embed_one, incident_text

    vec = embed_one(incident_text(text, symptoms))
    writes.set_vectors(g, "Incident", [{"id": inc, "embedding": vec}])


async def run(sid: str, investigator, tag: str | None = None, keep: bool = True, set_mode: bool = True,
              graph: str | None = None, nomem: bool = False):
    """One incident end to end. A scenario whose alerts INTAKE splits into several incidents needs run_all (this
    refuses rather than silently investigating only the first)."""
    from .agent.loop import run_incident

    lease = _lease_for(sid, set_mode)
    try:
        p = prepare(sid, tag, set_mode, graph=graph, nomem=nomem, lease=lease)
        if len(p.groups) > 1:
            if not keep:
                gcopy.delete_if_exists(gclient.engine(), p.graph)
            raise ValueError(f"{sid}: INTAKE opened {len(p.groups)} incidents; use scenario.run_all")
        res = await run_incident(tenant=p.tenant, incident_id=p.incident_id, onset_ms=p.onset_ms, symptoms=p.symptoms,
                                 investigator=investigator, graph=p.graph, run_id=p.run_id,
                                 window_min=p.scenario.get("window_min"))
    finally:
        if lease is not None:
            lease.release()
    if not keep:
        gcopy.delete_if_exists(gclient.engine(), p.graph)
    return p, res


def _lease_for(sid: str, set_mode: bool) -> Lease | None:
    """A whole-run hold on the warehouse for a data scenario that sets its mode (None otherwise)."""
    try:
        mode = load(sid).get("pipeline_mode") if set_mode else None
    except KeyError:
        return None
    return WAREHOUSE.reserve(mode) if mode else None


async def run_all(sid: str, investigator, tag: str | None = None, keep: bool = True, set_mode: bool = True,
                  graph: str | None = None, nomem: bool = False):
    """Every incident INTAKE opened, each investigated on its own (its own gate decides its own cause), then the
    scenario's later intake rounds (late alerts attach to the open incident whose confirmed origin reaches them, or
    open new ones, which are investigated too). Returns (prepared, [RunResult per incident, in opening order])."""
    lease = _lease_for(sid, set_mode)
    try:
        p = prepare(sid, tag, set_mode, graph=graph, nomem=nomem, lease=lease)
        try:
            results = await investigate_all(p, investigator)
        finally:
            if not keep:
                gcopy.delete_if_exists(gclient.engine(), p.graph)
    finally:
        if lease is not None:
            lease.release()
    return p, results


async def investigate_all(p: Prepared, investigator, on_open=None, on_done=None, on_start=None) -> list:
    """run_all's loop on an already prepared scenario: each onset incident in opening order, then each later intake
    round (whose alerts attach or open new incidents, investigated in turn). `on_open(round, [Opened])` runs when a
    round's incidents exist (before any of them is investigated), `on_start(Opened)` just before each one (it may
    raise to stop the loop, e.g. no LLM budget left), `on_done(Opened, RunResult)` after each one: the API indexes
    every incident's run through them."""
    from .agent.loop import run_incident

    results = []
    queue = list(p.groups)
    for k, window in enumerate([None] + late_rounds(p), 1):
        if window is not None:
            queue = list(intake_late(p, window[0], window[1], k).opened)
        if on_open is not None and queue:
            on_open(k, queue)
        for grp in queue:
            if on_start is not None:
                on_start(grp)
            res = await run_incident(tenant=p.tenant, incident_id=grp.incident_id, onset_ms=grp.onset_ms or p.onset_ms,
                                     symptoms=grp.symptoms, investigator=investigator, graph=p.graph,
                                     run_id=grp.run_id, window_min=p.scenario.get("window_min"))
            results.append(res)
            if on_done is not None:
                on_done(grp, res)
    return results


_ = Path
