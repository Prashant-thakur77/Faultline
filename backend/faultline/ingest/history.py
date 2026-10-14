"""Synthetic 120-day change and incident history for acme → Bundle (seed 42).

Pure and deterministic: no FalkorDB access, no wall clock (everything sits in
[clock.HISTORY_START_MS, clock.HISTORY_END_MS]), one `random.Random` stream, no set iteration.
People, teams, ownership and the on-call rota come from `org_gen.generate(seed)`.

Change domain
- Repo (one per team, `repo-<team>`) -CONTAINS-> File (`file:src/<service>/…`, `file:pipeline/transforms/…`)
- File -PART_OF-> Service | Transform (datastores and KPIs have no source files)
- Commit (`c-<sha8>`) authored with Zipf-weighted authorship per component; Person -AUTHORED-> Commit;
  Commit -TOUCHES {lines}-> File; Person -COMMITTED {n, last_at}-> Service | Transform (aggregate)
- PR (`pr-<n>`, state merged) -TOUCHES {lines}-> File, -CONTAINS-> Commit; Person -AUTHORED-> PR
- Deploy (`dep-<n>`, kind deploy | config | flag | data_cutover) -CHANGED {at}-> target, -CONTAINS-> Commit

Incident domain (40 incidents `inc-h001…`, six archetypes)
- Incident -HAS_SYMPTOM-> Symptom (`sym-<kind>-<target>`, shared by an archetype)
- Incident -AFFECTED {role, key}-> cause / symptom / impacted components
- Deploy -CAUSED-> Incident; Person -RESOLVED-> Incident; Incident -RESOLVED_BY-> Action (APPLIED), -ATTEMPTED-> Action (not applied)
- Postmortem (`pm-h<nnn>`) -DOCUMENTS-> Incident
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass, field

from . import org_gen
from .bundle import Bundle
from .clock import DAY_MS, HISTORY_DAYS, HISTORY_END_MS, HISTORY_START_MS, MINUTE_MS, day_start

TENANT = org_gen.TENANT
SEED_SALT = 1_000_003  # history uses its own stream so org changes don't reshuffle it

LANG_EXT = {
    "cpp": "cc", "typescript": "ts", "go": "go", "javascript": "js", "dotnet": "cs", "rust": "rs",
    "php": "php", "ruby": "rb", "python": "py", "java": "java", "kotlin": "kt", "elixir": "ex",
}
FILE_STEMS = ("main", "handler", "client", "server", "metrics", "retry", "routes", "models", "errors")
NAMED_FILES: dict[str, tuple[str, ...]] = {
    "payment": ("charge.js", "client.js", "index.js", "logger.js", "config.json"),
    "checkout": ("main.go", "place_order.go", "payment_client.go", "email_client.go", "config.yaml"),
    "product-catalog": ("main.go", "db.go", "products.go", "config.yaml"),
    "recommendation": ("recommendation_server.py", "cache.py", "catalog_client.py", "config.yaml"),
    "cart": ("CartService.cs", "ValkeyCartStore.cs", "Program.cs", "config.yaml"),
}

# Deploy frequency per component (relative). Unlisted components use DEFAULT_WEIGHT; KPIs never deploy.
DEPLOY_WEIGHT: dict[str, int] = {
    "payment": 10, "checkout": 8, "frontend": 8, "product-catalog": 7, "cart": 6, "recommendation": 6,
    "currency": 5, "quote": 5, "shipping": 4, "email": 3, "ad": 3, "accounting": 3, "fraud-detection": 3,
    "image-provider": 2, "frontend-proxy": 2, "flagd": 2, "chatbot": 2, "agent": 2, "mcp": 2,
    "flagd-ui": 1, "load-generator": 1, "cache": 2, "queue": 2, "astronomy-db": 2,
}
DEFAULT_WEIGHT = 2
COMMITS_PER_DEPLOY = (1, 1, 2, 2, 3, 4)
DEPLOYS_PER_DAY = (2, 3, 3, 4)
N_DATA_CUTOVERS = 2
DATA_CUTOVER_TARGET = "stg_fx_rates.sql"  # a reference-feed switch, the kind of change a cutover is

# Authorship: rank-r contributor gets weight 1/r^s. Components listed in DOMINANT_AUTHOR get a steep
# curve and a designated top author, so their bus factor is 1 (one person > 50% of commits);
# the bool says whether that person is still active (False = the expert has left).
ZIPF_S = 0.9
ZIPF_S_DOMINANT = 2.4
DOMINANT_AUTHOR: dict[str, bool] = {"quote": True, "currency": False}

RECENT_WINDOW_MS = 30 * DAY_MS
P_RESOLVER_ON_CALL = 0.3


@dataclass(frozen=True)
class Archetype:
    name: str
    count: int
    causes: tuple[str, ...]  # candidate cause components (first match in the org wins if filtered)
    kind: str  # deploy kind of the causing change
    symptom_kind: str
    symptom_target: str | None  # None = the first KPI
    impacted: tuple[str, ...]
    fixes: tuple[str, ...]  # Action kinds to draw from
    flag: str | None
    titles: tuple[str, ...]
    openings: tuple[str, ...]
    impacts: tuple[str, ...]


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "payment", 10, ("payment",), "deploy", "error_rate", "checkout", ("frontend",),
        ("rollback_deploy", "rollback_deploy", "flip_flag"), "paymentGate",
        ("Checkout errors after payment deploy", "Payment charge failures surface at checkout",
         "Spike in failed orders from payment charge errors"),
        ("Deploy {deploy} shipped a new build of {cause} and charge calls started failing, which showed up as "
         "a spike in {symptom} errors.",
         "Shortly after {deploy} rolled out to {cause}, {symptom} began returning failed orders to shoppers.",
         "A {cause} release ({deploy}) broke charge handling and the {symptom} error rate jumped within "
         "minutes of the rollout."),
        ("Orders placed through {impacted} were rejected until mitigation.",
         "Users of {impacted} saw failed order placements for the duration.", ""),
    ),
    Archetype(
        "catalog_lock", 7, ("astronomy-db",), "config", "latency", "product-catalog",
        ("frontend", "recommendation", "checkout"), ("rollback_deploy", "flip_flag"),
        "productCatalogLockContention",
        ("Product catalog latency from database lock contention",
         "Catalog lookups slow after database config change", "Lock waits on astronomy-db slow product pages"),
        ("A config change to {cause} ({deploy}) held long table locks and {symptom} queries queued behind them.",
         "Deploy {deploy} altered {cause} settings; lock contention pushed {symptom} latency far above its band.",
         "Lock waits on {cause} after {deploy} made {symptom} slow to answer product lookups."),
        ("Product pages on {impacted} loaded slowly and some checkouts timed out.",
         "Callers such as {impacted} inherited the slowdown through their catalog calls.", ""),
    ),
    Archetype(
        "recs_cache", 6, ("recommendation",), "deploy", "latency", "recommendation",
        ("product-catalog", "frontend"), ("flip_flag", "rollback_deploy"), "recommendationCacheFailure",
        ("Recommendation cache stampede", "Recommendation latency spike after cache reset",
         "Cold recommendation cache overloads product catalog"),
        ("Deploy {deploy} changed cache keys in {cause}, so the cache emptied at once and every request "
         "recomputed (a stampede).",
         "After {deploy}, {cause} lost its warm cache and latency climbed as all requests missed together.",
         "A {cause} release ({deploy}) invalidated its cache in one go and the stampede slowed {symptom}."),
        ("The recompute load spilled onto {impacted}.", "Both {impacted} saw elevated request volume from the misses.",
         ""),
    ),
    Archetype(
        "queue_lag", 6, ("queue",), "config", "lag", "queue", ("accounting", "fraud-detection"),
        ("rollback_deploy", "open_issue"), None,
        ("Order queue consumer lag", "Kafka consumer lag on order events", "Order event consumers fall behind"),
        ("Deploy {deploy} reduced {cause} partition throughput and consumer lag on {symptom} grew steadily.",
         "Consumers fell behind on {symptom} after a {cause} config change ({deploy}).",
         "Following {deploy}, {cause} rebalanced consumers repeatedly and lag built up on the order topic."),
        ("The {impacted} consumers processed order events hours late.", "Downstream consumers such as {impacted} fell behind.",
         ""),
    ),
    Archetype(
        "cart_cache", 5, ("cache",), "config", "error_rate", "cart", ("checkout", "frontend"),
        ("rollback_deploy", "flip_flag"), "cartFailure",
        ("Cart errors from cache failure", "Valkey cache refusing cart connections",
         "Cart service errors after cache config change"),
        ("Deploy {deploy} changed {cause} settings and {symptom} started failing reads and writes against it.",
         "A {cause} config push ({deploy}) evicted sessions and {symptom} returned errors when baskets could "
         "not be loaded.",
         "After {deploy}, connections to {cause} were refused and the {symptom} error rate rose sharply."),
        ("Shoppers on {impacted} lost their baskets.", "Requests from {impacted} could not load carts for a while.", ""),
    ),
    Archetype(
        "revenue_kpi", 6, ("fct_revenue.sql", "stg_orders.sql", "stg_fx_rates.sql", "exec_revenue_metric.sql"),
        "deploy", "kpi_jump", None, (), ("data_repair",), None,
        ("Executive revenue KPI anomaly after transform change", "Revenue KPI jump after pipeline edit",
         "Implausible executive revenue KPI value"),
        ("A change to {cause} ({deploy}) altered how amounts were aggregated and {symptom} jumped far outside "
         "its band.",
         "Deploy {deploy} shipped an edit to {cause} and the next pipeline run produced an implausible {symptom} value.",
         "After {deploy} touched {cause}, the revenue KPI ({symptom}) moved well beyond its trailing range."),
        ("",),
    ),
)

FIX_SENTENCES: dict[str, tuple[str, ...]] = {
    "rollback_deploy": (
        "We rolled back {deploy} and the metrics returned to baseline.",
        "Rolling {cause} back to the previous release cleared the problem.",
        "Reverting {deploy} restored normal behaviour within minutes.",
    ),
    "flip_flag": (
        "Flipping the {flag} flag contained the impact until a fixed build shipped.",
        "The on-call engineer flipped {flag}, which isolated {cause} and stopped the damage.",
    ),
    "data_repair": (
        "We reverted the transform, rebuilt the affected tables and re-ran the invariants before "
        "re-publishing the KPI.",
        "A data repair of {cause} plus a rebuild brought the KPI back in band.",
    ),
    "open_issue": (
        "The previous settings were restored and a follow-up issue was opened to tune {cause} capacity.",
        "A follow-up issue was opened against {cause} once the config was restored.",
    ),
}
NOT_APPLIED_SENTENCE = "A first attempt to flip {flag} did not take effect, so the team rolled back {deploy} instead."
NOT_APPLIED_ARCHETYPE = "payment"
NOT_APPLIED_ORDINAL = 2  # the third incident of that archetype (0-based) gets the failed first action

COMMIT_VERBS = ("fix", "feat", "refactor", "perf", "chore")
COMMIT_OBJECTS = (
    "tighten error handling", "add request metrics", "bump client library", "simplify retry loop",
    "clean up logging", "handle empty responses", "tune connection pool", "add input validation",
    "update config defaults", "improve timeout handling", "split handler", "cache lookups",
)


def _and(items: tuple[str, ...]) -> str:
    """'a', 'a and b', 'a, b and c' (for postmortem prose)."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def symptom_id(kind: str, target: str) -> str:
    return f"sym-{kind}-{target}"


def file_id(path: str) -> str:
    return f"file:{path}"


@dataclass
class _Commit:
    sha: str
    at: int
    author: str
    component: str
    title: str
    lines: dict[str, int]  # file id -> lines

    @property
    def id(self) -> str:
        return f"c-{self.sha[:8]}"


@dataclass
class _PR:
    merged_at: int
    author: str
    title: str
    repo: str
    commits: list[_Commit]
    id: str = ""


@dataclass
class _Deploy:
    at: int
    target: str
    kind: str
    actor: str
    sha: str
    commits: list[_Commit] = field(default_factory=list)
    pr: _PR | None = None
    flag: str | None = None
    archetype: Archetype | None = None
    id: str = ""


class _Gen:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.org = org_gen.generate(seed)
        self.rng = random.Random(seed * SEED_SALT + 7)
        self.topo = org_gen.load_topology()
        self.lang = {s["id"]: s["lang"] for s in self.topo["services"]}
        self.flags_for = self._flags_for()
        self.files = self._files()
        self.pools = self._pools()
        self.sha_counter = 0

    # ---------- static structure ----------
    def _flags_for(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f in self.topo.get("flags", []):
            svc = str(f["gates"]).split(":")[0]
            out.setdefault(svc, []).append(f["id"])
        return out

    def _files(self) -> dict[str, list[str]]:
        files: dict[str, list[str]] = {}
        for comp, label in self.org.components.items():
            if label == "Service":
                names = NAMED_FILES.get(comp)
                if names is None:
                    ext = LANG_EXT[self.lang[comp]]
                    names = (*(f"{s}.{ext}" for s in self.rng.sample(FILE_STEMS, 3)), "config.yaml")
                files[comp] = [file_id(f"src/{comp}/{n}") for n in names]
            elif label == "Transform":
                files[comp] = [file_id(f"pipeline/transforms/{comp}")]
        return files

    def _pools(self) -> dict[tuple[str, str], list[str]]:
        """Ranked contributor list per (component, owning team); the rank drives Zipf weights."""
        org = self.org
        engineers = [p.id for p in org.people if p.role == "engineer"]
        pools: dict[tuple[str, str], list[str]] = {}
        for comp in sorted(self.files):
            teams = sorted({o.team for o in org.ownership if o.component == comp})
            for team in teams:
                ranked = list(org.members[team])
                self.rng.shuffle(ranked)
                helper = self.rng.choice([e for e in engineers if org.person(e).team != team])
                ranked.append(helper)
                if comp in DOMINANT_AUTHOR and team == org.current_owner(comp):
                    want_active = DOMINANT_AUTHOR[comp]
                    cands = [p for p in org.members[team][1:] if org.person(p).active == want_active]
                    if not cands:
                        raise ValueError(f"no {'active' if want_active else 'inactive'} engineer in {team} for {comp}")
                    top = max(cands, key=lambda p: (org.person(p).valid_to or 0, p)) if not want_active \
                        else self.rng.choice(cands)
                    ranked.remove(top)
                    ranked.insert(0, top)
                pools[(comp, team)] = ranked
        return pools

    # ---------- primitives ----------
    def _sha(self, *parts: object) -> str:
        self.sha_counter += 1
        raw = ":".join(str(p) for p in (TENANT, self.seed, self.sha_counter, *parts))
        return hashlib.sha1(raw.encode()).hexdigest()

    def _author(self, comp: str, t: int) -> str:
        team = self.org.owner_at(comp, t)
        ranked = self.pools[(comp, team)]
        s = ZIPF_S_DOMINANT if comp in DOMINANT_AUTHOR else ZIPF_S
        cands = [(p, 1.0 / (i + 1) ** s) for i, p in enumerate(ranked) if self.org.person(p).active_at(t)]
        return self.rng.choices([p for p, _ in cands], weights=[w for _, w in cands], k=1)[0]

    def _on_call(self, comp: str, t: int) -> str:
        team = self.org.owner_at(comp, t)
        return self.org.on_call_at(team, t) or self.org.lead_of(team)

    def _commits(self, comp: str, merged_at: int, config_only: bool) -> list[_Commit]:
        rng = self.rng
        n = 1 if config_only else rng.choice(COMMITS_PER_DEPLOY)
        out = []
        for _ in range(n):
            at = max(HISTORY_START_MS, merged_at - rng.randint(10, 2 * 24 * 60) * MINUTE_MS)
            author = self._author(comp, at)
            pool = self.files[comp]
            if config_only:
                touched = [f for f in pool if f.endswith(("config.yaml", "config.json"))][:1] or pool[:1]
            else:
                touched = sorted(rng.sample(pool, k=min(len(pool), rng.choice((1, 1, 2, 3)))))
            lines = {f: min(400, int(rng.paretovariate(1.2) * 6)) for f in touched}
            title = ("chore" if config_only else rng.choice(COMMIT_VERBS)) + f"({comp}): " + (
                "update runtime config" if config_only else rng.choice(COMMIT_OBJECTS))
            out.append(_Commit(self._sha(comp, at), at, author, comp, title, lines))
        out.sort(key=lambda c: (c.at, c.sha))
        return out

    def _deploy(self, comp: str, kind: str, at: int) -> _Deploy:
        """Build one change of `kind` to `comp` at `at`, with its commits/PR when it ships code."""
        rng = self.rng
        label = self.org.components[comp]
        if kind in ("deploy", "config") and label in ("Service", "Transform"):
            merged_at = at - rng.randint(15, 180) * MINUTE_MS
            commits = self._commits(comp, merged_at, config_only=(kind == "config"))
            repo = f"repo-{self.org.current_owner(comp)}"
            pr = _PR(merged_at, commits[0].author, commits[0].title, repo, commits)
            actor = pr.author if self.org.person(pr.author).active_at(at) else self._on_call(comp, at)
            return _Deploy(at, comp, kind, actor, commits[-1].sha, commits, pr)
        flag = rng.choice(self.flags_for[comp]) if kind == "flag" else None
        return _Deploy(at, comp, kind, self._on_call(comp, at), self._sha("change", comp, kind, at), flag=flag)

    def _random_change(self, at: int, avoid: str | None) -> _Deploy:
        rng = self.rng
        comps = [c for c, label in self.org.components.items() if label != "KPI" and c != avoid]
        weights = [DEPLOY_WEIGHT.get(c, DEFAULT_WEIGHT) for c in comps]
        comp = rng.choices(comps, weights=weights, k=1)[0]
        label = self.org.components[comp]
        if label == "Datastore":
            kind = "config"
        elif label == "Transform":
            kind = "deploy"
        else:
            r = rng.random()
            kind = "flag" if r < 0.09 and comp in self.flags_for else ("config" if r < 0.14 else "deploy")
        return self._deploy(comp, kind, at)

    # ---------- the timeline ----------
    def timeline(self) -> tuple[list[_Deploy], list[_PR]]:
        rng = self.rng
        n_days = HISTORY_DAYS - 1  # day 0 … day 118: every event ends before ANCHOR − 1 day
        plan = [a for a in ARCHETYPES for _ in range(a.count)]
        rng.shuffle(plan)
        incident_days = sorted(rng.sample(range(2, n_days), len(plan)))
        by_day = dict(zip(incident_days, plan))
        free_days = [d for d in range(2, n_days) if d not in by_day]
        cutover_days = sorted(rng.sample(free_days, N_DATA_CUTOVERS))
        transforms = [c for c, label in self.org.components.items() if label == "Transform"]

        deploys: list[_Deploy] = []
        for d in range(n_days):
            k = rng.choice(DEPLOYS_PER_DAY)
            minutes = sorted(rng.randint(9 * 60, 18 * 60) for _ in range(k))
            arche = by_day.get(d)
            cause_slot = rng.randrange(k) if arche else -1
            cause_comp = None
            if arche:
                cands = [c for c in arche.causes if c in self.org.components] or transforms
                cause_comp = rng.choice(cands)
            for i, m in enumerate(minutes):
                at = day_start(d) + m * MINUTE_MS
                if i == cause_slot and arche and cause_comp:
                    dep = self._deploy(cause_comp, arche.kind, at)
                    dep.archetype = arche
                else:
                    dep = self._random_change(at, avoid=cause_comp)
                deploys.append(dep)
            if d in cutover_days and DATA_CUTOVER_TARGET in self.org.components:
                at = day_start(d) + rng.randint(6 * 60, 8 * 60) * MINUTE_MS
                deploys.append(self._deploy(DATA_CUTOVER_TARGET, "data_cutover", at))
        deploys.sort(key=lambda x: (x.at, x.sha))
        for i, dep in enumerate(deploys, start=1):
            dep.id = f"dep-{i}"
        prs = sorted((d.pr for d in deploys if d.pr), key=lambda p: (p.merged_at, p.commits[0].sha))
        for i, pr in enumerate(prs, start=101):
            pr.id = f"pr-{i}"
        return deploys, prs


def _kpi(org: org_gen.Org) -> str:
    return next(c for c, label in org.components.items() if label == "KPI")


def build(seed: int = 42) -> Bundle:
    g = _Gen(seed)
    org, rng = g.org, g.rng
    deploys, prs = g.timeline()
    commits = [c for d in deploys for c in d.commits]
    if len({c.id for c in commits}) != len(commits):
        raise ValueError("commit id collision (sha8); change SEED_SALT")
    if commits and (min(c.at for c in commits) < HISTORY_START_MS or max(d.at for d in deploys) > HISTORY_END_MS):
        raise ValueError("generated history escapes its window")
    label = org.components

    b = Bundle()
    # repos and files
    for tid, name in org.teams:
        b.node("Repo", f"repo-{tid}", tenant=TENANT, name=f"{name} monorepo", team_id=tid,
               url=f"https://git.acme.example/repo-{tid}")
    for comp in sorted(g.files):
        repo = f"repo-{org.current_owner(comp)}"
        for fid in g.files[comp]:
            path = fid.removeprefix("file:")
            b.node("File", fid, tenant=TENANT, path=path, repo_id=repo, component_id=comp)
            b.edge("PART_OF", "File", fid, label[comp], comp)
            b.edge("CONTAINS", "Repo", repo, "File", fid)

    # commits, PRs, deploys
    committed: dict[tuple[str, str], list[int]] = {}
    for c in sorted(commits, key=lambda c: (c.at, c.sha)):
        b.node("Commit", c.id, tenant=TENANT, sha=c.sha, at=c.at, author_id=c.author, title=c.title,
               repo_id=f"repo-{org.current_owner(c.component)}", component_id=c.component)
        b.edge("AUTHORED", "Person", c.author, "Commit", c.id, at=c.at)
        for fid, n in sorted(c.lines.items()):
            b.edge("TOUCHES", "Commit", c.id, "File", fid, lines=n)
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
            b.edge("CONTAINS", "PR", pr.id, "Commit", c.id)
        for fid, n in sorted(lines.items()):
            b.edge("TOUCHES", "PR", pr.id, "File", fid, lines=n)
    for d in deploys:
        props = {"tenant": TENANT, "target_id": d.target, "sha": d.sha, "at": d.at, "kind": d.kind,
                 "actor_id": d.actor}
        if d.pr:
            props["pr_id"] = d.pr.id
        if d.flag:
            props["flag_id"] = d.flag
        b.node("Deploy", d.id, **props)
        b.edge("CHANGED", "Deploy", d.id, label[d.target], d.target, at=d.at)
        for c in d.commits:
            b.edge("CONTAINS", "Deploy", d.id, "Commit", c.id)

    # incidents
    kpi = _kpi(org)
    seen_symptoms: list[str] = []
    ordinal: Counter[str] = Counter()
    causes = [d for d in deploys if d.archetype is not None]
    for n, dep in enumerate(causes, start=1):
        a = dep.archetype
        if a is None:  # pragma: no cover - filtered above
            continue
        iid, pmid = f"inc-h{n:03d}", f"pm-h{n:03d}"
        onset = dep.at + rng.randint(3, 20) * MINUTE_MS
        opened = onset + rng.randint(2, 10) * MINUTE_MS
        resolved = opened + rng.randint(25, 200) * MINUTE_MS
        title = rng.choice(a.titles)
        b.node("Incident", iid, tenant=TENANT, title=title, stage="RESOLVED", opened_at=opened, onset_at=onset,
               resolved_at=resolved, salience_base=1.0, salience=1.0, last_used=resolved, confident=True)

        sym_target = a.symptom_target or kpi
        sid = symptom_id(a.symptom_kind, sym_target)
        if sid not in seen_symptoms:
            seen_symptoms.append(sid)
            b.node("Symptom", sid, tenant=TENANT, kind=a.symptom_kind, target_id=sym_target)
        b.edge("HAS_SYMPTOM", "Incident", iid, "Symptom", sid)
        b.edge("AFFECTED", "Incident", iid, label[dep.target], dep.target, role="cause", key="cause")
        b.edge("AFFECTED", "Incident", iid, label[sym_target], sym_target, role="symptom", key="symptom")
        for imp in a.impacted:
            b.edge("AFFECTED", "Incident", iid, label[imp], imp, role="impacted", key="impacted")
        b.edge("CAUSED", "Deploy", dep.id, "Incident", iid, at=onset)

        resolver = _resolver(g, dep.target, onset, commits)
        b.edge("RESOLVED", "Person", resolver, "Incident", iid, at=resolved)

        failed_first = a.name == NOT_APPLIED_ARCHETYPE and ordinal[a.name] == NOT_APPLIED_ORDINAL
        ordinal[a.name] += 1
        fix = "rollback_deploy" if failed_first else rng.choice(a.fixes)
        fmt = {"deploy": dep.id, "cause": dep.target, "symptom": sym_target, "flag": a.flag or "",
               "impacted": _and(a.impacted)}
        actions: list[tuple[str, str, int, str]] = []
        if failed_first:
            actions.append(("flip_flag", "NOT_APPLIED", opened + 12 * MINUTE_MS,
                             "second channel re-read still showed the old flag value; the change did not take"))
        actions.append((fix, "APPLIED", resolved - 4 * MINUTE_MS,
                        "second channel confirmed the symptom metric back inside its baseline band"))
        for k, (kind, verdict, at, why) in enumerate(actions, start=1):
            target = {"rollback_deploy": dep.id, "flip_flag": a.flag or dep.target,
                      "data_repair": dep.target}.get(kind, dep.target)
            aid = f"act-h{n:03d}-{k}"
            b.node("Action", aid, tenant=TENANT, kind=kind, target_id=target, verdict=verdict, at=at,
                   explanation=why, incident_id=iid)
            b.edge("RESOLVED_BY" if verdict == "APPLIED" else "ATTEMPTED", "Incident", iid, "Action", aid)

        sentences = [rng.choice(a.openings)]
        impact = rng.choice(a.impacts)
        if impact:
            sentences.append(impact)
        sentences.append(NOT_APPLIED_SENTENCE if failed_first else rng.choice(FIX_SENTENCES[fix]))
        summary = " ".join(s.format(**fmt) for s in sentences)
        b.node("Postmortem", pmid, tenant=TENANT, incident_id=iid, summary=summary,
               url=f"docs/postmortems/{pmid}.md")
        b.edge("DOCUMENTS", "Postmortem", pmid, "Incident", iid)
    return b


def _resolver(g: _Gen, cause: str, onset: int, commits: list[_Commit]) -> str:
    """Prefer the cause component's recent, still-present committers; sometimes the owner's on-call."""
    org, rng = g.org, g.rng
    recent = Counter(c.author for c in commits
                     if c.component == cause and onset - RECENT_WINDOW_MS <= c.at < onset
                     and org.person(c.author).active_at(onset))
    on_call = g._on_call(cause, onset)
    if not recent or rng.random() < P_RESOLVER_ON_CALL:
        return on_call
    people = sorted(recent)
    return rng.choices(people, weights=[recent[p] for p in people], k=1)[0]
