"""globex 120-day change and incident history → Bundle (same shapes as `ingest/history.py`).

Reuses acme's generator primitives (`history._Gen`: files per service, Zipf authorship pools, commits, PRs,
deploys, resolver choice) with globex's topology, org and spec, and ids prefixed `gx-` so nothing can collide
with acme: Repo `repo-<team>`, File `file:src/<service>/…`, Commit `gx-c-<sha8>`, PR `gx-pr-<n>`, Deploy
`gx-dep-<n>`, Incident `gx-inc-<nnn>`, Postmortem `gx-pm-<nnn>`, Action `gx-act-<nnn>-<k>`, Symptom
`sym-<kind>-<target>` (shared by an archetype family).

150 incidents in eight families (spec `archetypes`); up to two incidents a day. Each has HAS_SYMPTOM, AFFECTED
{role: cause | symptom | impacted}, Deploy -CAUSED->, Person -RESOLVED->, -RESOLVED_BY-> Action {kind,
target_id, verdict APPLIED (one family member also has a NOT_APPLIED first attempt)} and a Postmortem.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from functools import lru_cache
from types import SimpleNamespace

from .. import history as H
from ..bundle import Bundle
from ..clock import HISTORY_DAYS, HISTORY_END_MS, HISTORY_START_MS, MINUTE_MS, day_start
from . import TENANT, load_spec, org, topology

SEED_SALT = 2_000_029
P_FLAG_CHANGE = 0.06
P_CONFIG_CHANGE = 0.12


def _archetypes(spec: dict) -> list[tuple[H.Archetype, int | None]]:
    out = []
    for a in spec["archetypes"]:
        sym = a["symptom"]
        arch = H.Archetype(
            a["name"], int(a["count"]), tuple(a["causes"]), a["kind"], sym["kind"], sym["target"],
            tuple(a["impacted"]), tuple(a["fixes"]), a.get("flag"), tuple(a["titles"]), tuple(a["openings"]),
            tuple(a["impacts"]),
        )
        out.append((arch, a.get("not_applied_ordinal")))
    return out


class _GlobexGen(H._Gen):
    """acme's generator with globex's world. Only the parts that hard-code acme are overridden."""

    def __init__(self, seed: int) -> None:  # noqa: D107 - deliberately does not call H._Gen.__init__ (acme world)
        self.seed = seed
        self.spec = load_spec()
        self.world = topology.generate(seed)
        self.org = org.generate(seed)
        self.rng = random.Random(seed * SEED_SALT + 11)
        self.lang = {s["id"]: s["lang"] for s in self.world.services}
        self.flags_for = self._globex_flags_for()
        cfg = self.spec["org"]
        self.dominant: dict[str, bool] = {cfg["departed_expert"]["component"]: False}
        self.dominant.update({c: True for c in cfg["dominant_active"]})
        self.deploy_weight: dict[str, int] = dict(self.spec["history"]["deploy_weight"])
        self.files = self._files()
        self.pools = self._pools()
        self.sha_counter = 0

    def _globex_flags_for(self) -> dict[str, list[str]]:
        eps = {e["id"]: e["service"] for e in self.world.endpoints}
        out: dict[str, list[str]] = {}
        for f in self.world.flags:
            svc = eps.get(f["gates"], f["gates"])
            out.setdefault(svc, []).append(f["id"])
        return out

    def _pools(self) -> dict[tuple[str, str], list[str]]:
        org_ = self.org
        engineers = [p.id for p in org_.people if p.role == "engineer"]
        pools: dict[tuple[str, str], list[str]] = {}
        for comp in sorted(self.files):
            teams = sorted({o.team for o in org_.ownership if o.component == comp})
            for team in teams:
                ranked = list(org_.members[team])
                self.rng.shuffle(ranked)
                ranked.append(self.rng.choice([e for e in engineers if org_.person(e).team != team]))
                if comp in self.dominant and team == org_.current_owner(comp):
                    want_active = self.dominant[comp]
                    cands = [p for p in org_.members[team][1:] if org_.person(p).active == want_active]
                    if not cands:
                        raise ValueError(f"no {'active' if want_active else 'inactive'} engineer in {team} for {comp}")
                    if want_active:
                        top = self.rng.choice(cands)
                    else:  # the most recently departed engineer is the expert who left
                        top = max(cands, key=lambda p: (org_.person(p).valid_to or 0, p))
                    ranked.remove(top)
                    ranked.insert(0, top)
                pools[(comp, team)] = ranked
        return pools

    def _sha(self, *parts: object) -> str:
        self.sha_counter += 1
        raw = ":".join(str(p) for p in (TENANT, self.seed, self.sha_counter, *parts))
        return hashlib.sha1(raw.encode()).hexdigest()

    def _author(self, comp: str, t: int) -> str:
        team = self.org.owner_at(comp, t)
        ranked = self.pools[(comp, team)]
        s = H.ZIPF_S_DOMINANT if comp in self.dominant else H.ZIPF_S
        cands = [(p, 1.0 / (i + 1) ** s) for i, p in enumerate(ranked) if self.org.person(p).active_at(t)]
        return self.rng.choices([p for p, _ in cands], weights=[w for _, w in cands], k=1)[0]

    def _random_change(self, at: int, avoid: str | None) -> H._Deploy:
        rng = self.rng
        default = int(self.spec["history"]["default_weight"])
        comps = [c for c in self.org.components if c != avoid]
        comp = rng.choices(comps, weights=[self.deploy_weight.get(c, default) for c in comps], k=1)[0]
        if self.org.components[comp] == "Datastore":
            kind = "config"
        else:
            r = rng.random()
            kind = "flag" if r < P_FLAG_CHANGE and comp in self.flags_for else (
                "config" if r < P_CONFIG_CHANGE else "deploy")
        return self._deploy(comp, kind, at)

    def timeline(self) -> tuple[list[H._Deploy], list[H._PR]]:
        rng = self.rng
        cfg = self.spec["history"]
        n_days = HISTORY_DAYS - 1  # day 0 … day 118: every event ends before ANCHOR − 1 day
        plan = [a for a, _ in _archetypes(self.spec) for _ in range(a.count)]
        rng.shuffle(plan)
        slots = [(d, s) for d in range(2, n_days) for s in range(int(cfg["max_incidents_per_day"]))]
        chosen = sorted(rng.sample(slots, len(plan)))
        by_day: dict[int, list[H.Archetype]] = {}
        for (d, _), arche in zip(chosen, plan):
            by_day.setdefault(d, []).append(arche)

        deploys: list[H._Deploy] = []
        for d in range(n_days):
            todays = by_day.get(d, [])
            k = max(rng.choice(tuple(cfg["deploys_per_day"])), len(todays) + 1)
            minutes = sorted(rng.randint(8 * 60, 19 * 60) for _ in range(k))
            cause_slots = dict(zip(sorted(rng.sample(range(k), len(todays))), todays))
            causes = {i: rng.choice([c for c in a.causes if c in self.org.components]) for i, a in cause_slots.items()}
            avoid = next(iter(causes.values()), None)
            for i, m in enumerate(minutes):
                at = day_start(d) + m * MINUTE_MS
                if i in cause_slots:
                    dep = self._deploy(causes[i], cause_slots[i].kind, at)
                    dep.archetype = cause_slots[i]
                else:
                    dep = self._random_change(at, avoid=avoid)
                deploys.append(dep)
        deploys.sort(key=lambda x: (x.at, x.sha))
        for i, dep in enumerate(deploys, start=1):
            dep.id = f"gx-dep-{i}"
        prs = sorted((d.pr for d in deploys if d.pr), key=lambda p: (p.merged_at, p.commits[0].sha))
        for i, pr in enumerate(prs, start=101):
            pr.id = f"gx-pr-{i}"
        return deploys, prs


def commit_id(c: H._Commit) -> str:
    return f"gx-{c.id}"


@lru_cache(maxsize=2)
def _generated(seed: int) -> tuple[_GlobexGen, list[H._Deploy], list[H._PR]]:
    g = _GlobexGen(seed)
    deploys, prs = g.timeline()
    return g, deploys, prs


def build(seed: int = 42) -> Bundle:
    g, deploys, prs = _generated(seed)
    org_, spec = g.org, g.spec
    rng = random.Random(seed * SEED_SALT + 13)  # incident details: independent of the timeline stream
    commits = [c for d in deploys for c in d.commits]
    if len({c.id for c in commits}) != len(commits):
        raise ValueError("commit id collision (sha8); change SEED_SALT")
    if commits and (min(c.at for c in commits) < HISTORY_START_MS or max(d.at for d in deploys) > HISTORY_END_MS):
        raise ValueError("generated history escapes its window")
    label = org_.components
    host = spec["host"]

    b = Bundle()
    for tid, name in org_.teams:
        b.node("Repo", f"repo-{tid}", tenant=TENANT, name=f"{name} monorepo", team_id=tid,
               url=f"https://{host}/repo-{tid}")
    for comp in sorted(g.files):
        repo = f"repo-{org_.current_owner(comp)}"
        for fid in g.files[comp]:
            b.node("File", fid, tenant=TENANT, path=fid.removeprefix("file:"), repo_id=repo, component_id=comp)
            b.edge("PART_OF", "File", fid, label[comp], comp)
            b.edge("CONTAINS", "Repo", repo, "File", fid)

    committed: dict[tuple[str, str], list[int]] = {}
    for c in sorted(commits, key=lambda c: (c.at, c.sha)):
        cid = commit_id(c)
        b.node("Commit", cid, tenant=TENANT, sha=c.sha, at=c.at, author_id=c.author, title=c.title,
               repo_id=f"repo-{org_.current_owner(c.component)}", component_id=c.component)
        b.edge("AUTHORED", "Person", c.author, "Commit", cid, at=c.at)
        for fid, n in sorted(c.lines.items()):
            b.edge("TOUCHES", "Commit", cid, "File", fid, lines=n)
        agg = committed.setdefault((c.author, c.component), [0, 0])
        agg[0] += 1
        agg[1] = max(agg[1], c.at)
    for (pid, comp), (n, last_at) in sorted(committed.items()):
        b.edge("COMMITTED", "Person", pid, label[comp], comp, n=n, last_at=last_at)
    for pr in prs:
        b.node("PR", pr.id, tenant=TENANT, title=pr.title, author_id=pr.author, merged_at=pr.merged_at,
               state="merged", repo_id=pr.repo)
        b.edge("AUTHORED", "Person", pr.author, "PR", pr.id, at=pr.merged_at)
        lines: Counter[str] = Counter()
        for c in pr.commits:
            lines.update(c.lines)
            b.edge("CONTAINS", "PR", pr.id, "Commit", commit_id(c))
        for fid, n in sorted(lines.items()):
            b.edge("TOUCHES", "PR", pr.id, "File", fid, lines=n)
    for d in deploys:
        props = {"tenant": TENANT, "target_id": d.target, "sha": d.sha, "at": d.at, "kind": d.kind, "actor_id": d.actor}
        if d.pr:
            props["pr_id"] = d.pr.id
        if d.flag:
            props["flag_id"] = d.flag
        b.node("Deploy", d.id, **props)
        b.edge("CHANGED", "Deploy", d.id, label[d.target], d.target, at=d.at)
        for c in d.commits:
            b.edge("CONTAINS", "Deploy", d.id, "Commit", commit_id(c))

    not_applied = {a.name: o for a, o in _archetypes(spec) if o is not None}
    seen_symptoms: list[str] = []
    ordinal: Counter[str] = Counter()
    resolver_ctx = SimpleNamespace(org=org_, rng=rng, _on_call=g._on_call)  # what H._resolver reads (cached g untouched)
    for n, dep in enumerate((d for d in deploys if d.archetype is not None), start=1):
        a = dep.archetype
        assert a is not None
        iid, pmid = f"gx-inc-{n:03d}", f"gx-pm-{n:03d}"
        onset = dep.at + rng.randint(3, 20) * MINUTE_MS
        opened = onset + rng.randint(2, 10) * MINUTE_MS
        resolved = opened + rng.randint(25, 200) * MINUTE_MS
        b.node("Incident", iid, tenant=TENANT, title=rng.choice(a.titles), stage="RESOLVED", opened_at=opened,
               onset_at=onset, resolved_at=resolved, salience_base=1.0, salience=1.0, last_used=resolved,
               confident=True)
        sym_target = a.symptom_target or dep.target
        sid = H.symptom_id(a.symptom_kind, sym_target)
        if sid not in seen_symptoms:
            seen_symptoms.append(sid)
            b.node("Symptom", sid, tenant=TENANT, kind=a.symptom_kind, target_id=sym_target)
        b.edge("HAS_SYMPTOM", "Incident", iid, "Symptom", sid)
        b.edge("AFFECTED", "Incident", iid, label[dep.target], dep.target, role="cause", key="cause")
        b.edge("AFFECTED", "Incident", iid, label[sym_target], sym_target, role="symptom", key="symptom")
        for imp in a.impacted:
            b.edge("AFFECTED", "Incident", iid, label[imp], imp, role="impacted", key="impacted")
        b.edge("CAUSED", "Deploy", dep.id, "Incident", iid, at=onset)
        resolver = H._resolver(resolver_ctx, dep.target, onset, commits)  # type: ignore[arg-type]
        b.edge("RESOLVED", "Person", resolver, "Incident", iid, at=resolved)

        failed_first = not_applied.get(a.name) == ordinal[a.name]
        ordinal[a.name] += 1
        fix = "rollback_deploy" if failed_first else rng.choice(a.fixes)
        if fix == "flip_flag" and not a.flag:
            fix = "rollback_deploy"
        fmt = {"deploy": dep.id, "cause": dep.target, "symptom": sym_target, "flag": a.flag or "",
               "impacted": H._and(a.impacted)}
        actions: list[tuple[str, str, int, str]] = []
        if failed_first and a.flag:
            actions.append(("flip_flag", "NOT_APPLIED", opened + 12 * MINUTE_MS,
                            "second channel re-read still showed the old flag value; the change did not take"))
        actions.append((fix, "APPLIED", resolved - 4 * MINUTE_MS,
                        "second channel confirmed the symptom metric back inside its baseline band"))
        for k, (kind, verdict, at, why) in enumerate(actions, start=1):
            target = {"rollback_deploy": dep.id, "flip_flag": a.flag or dep.target}.get(kind, dep.target)
            aid = f"gx-act-{n:03d}-{k}"
            b.node("Action", aid, tenant=TENANT, kind=kind, target_id=target, verdict=verdict, at=at,
                   explanation=why, incident_id=iid)
            b.edge("RESOLVED_BY" if verdict == "APPLIED" else "ATTEMPTED", "Incident", iid, "Action", aid)

        sentences = [rng.choice(a.openings)]
        impact = rng.choice(a.impacts)
        if impact:
            sentences.append(impact)
        sentences.append(H.NOT_APPLIED_SENTENCE if failed_first and a.flag else rng.choice(H.FIX_SENTENCES[fix]))
        b.node("Postmortem", pmid, tenant=TENANT, incident_id=iid, summary=" ".join(s.format(**fmt) for s in sentences),
               url=f"docs/postmortems/{pmid}.md")
        b.edge("DOCUMENTS", "Postmortem", pmid, "Incident", iid)
    return b
