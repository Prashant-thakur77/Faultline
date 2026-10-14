"""Synthetic acme organisation → Bundle (seed 42).

Pure and deterministic: no FalkorDB access, no wall clock (times derive from `clock.ANCHOR_MS`),
one `random.Random(seed)` stream, and no iteration over unordered sets. All names are synthetic.

Nodes: Team {name}, Person {name, role, active, valid_to}.
Edges: MEMBER_OF {from, to}, REPORTS_TO {from} (engineers → team lead → director → VP),
ON_CALL {from, to, key} (weekly rota per team, contiguous, ANCHOR−120d … ANCHOR+30d),
COLLABORATES {w} (symmetric: one edge each way, same weight),
OWNS (current owner, exactly one per component) and OWNED_AT {from, to, key} (every ownership
period, including the current one, which has no `to`).

`generate()` returns the `Org` model that `history.py` also uses (owner at a time, on-call at a
time, who was active when), so both producers agree on one org.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .bundle import Bundle
from .clock import ANCHOR_MS, DAY_MS, HOUR_MS, ORG_EPOCH_MS, ROTA_END_MS, ROTA_START_MS, WEEK_MS

TENANT = "acme"
REPO_ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY_PATH = REPO_ROOT / "data" / "topology" / "otel-demo.yaml"
LINEAGE_DIR = REPO_ROOT / "data" / "fixtures" / "lineage"

def team_node_id(key: str) -> str:
    """Graph id of a team (prefixed so it can never collide with a component id like `checkout`)."""
    return f"team-{key}"


TEAMS: tuple[tuple[str, str], ...] = (
    ("payments", "Payments"),
    ("checkout", "Checkout"),
    ("catalog", "Catalog"),
    ("storefront", "Storefront"),
    ("platform", "Platform"),
    ("data", "Data"),
    ("growth", "Growth"),
    ("assistant", "Assistant"),
)

# Current ownership of the OTel Demo services and datastores. The data team owns the lineage
# Transforms and KPIs (read from data/fixtures/lineage when present).
TEAM_OWNS: dict[str, tuple[str, ...]] = {
    "payments": ("payment",),
    "checkout": ("checkout", "email", "queue"),
    "catalog": ("product-catalog", "astronomy-db", "quote"),
    "storefront": ("frontend", "frontend-proxy", "image-provider", "cart", "cache", "currency", "shipping"),
    "growth": ("recommendation", "ad"),
    "platform": ("flagd", "flagd-ui", "load-generator", "accounting", "fraud-detection"),
    "assistant": ("chatbot", "agent", "mcp"),
    "data": (),
}
DATA_TEAM = "data"
DEFAULT_TRANSFORMS: tuple[str, ...] = (
    "stg_orders.sql", "stg_customers.sql", "stg_fx_rates.sql", "fct_revenue.sql", "exec_revenue_metric.sql",
)
DEFAULT_KPIS: tuple[str, ...] = ("kpi.exec_revenue",)

# (component, previous owner, current owner, days before ANCHOR the move happened)
OWNERSHIP_CHANGES: tuple[tuple[str, str, str, int], ...] = (
    ("ad", "storefront", "growth", 45),
    ("fraud-detection", "payments", "platform", 70),
)

# Directors split the eight teams; leads report to them; directors report to the VP.
DIRECTOR_TEAMS: tuple[tuple[str, ...], ...] = (
    ("payments", "checkout", "catalog", "storefront"),
    ("platform", "data", "growth", "assistant"),
)
ENGINEERS_PER_TEAM: dict[str, int] = {
    "payments": 4, "checkout": 4, "catalog": 4, "storefront": 4,
    "platform": 4, "data": 3, "growth": 3, "assistant": 3,
}
N_PEOPLE = 40
N_INACTIVE = 4
# One inactive engineer must come from this team: the history makes them the dominant (and now
# departed) author of one of its components, so the bus-factor warning has a real case.
INACTIVE_REQUIRED_TEAM = "storefront"
INACTIVE_REQUIRED_DAYS_AGO = 12

FIRST_NAMES = (
    "Amara", "Bastian", "Calla", "Dorian", "Elsbeth", "Florin", "Greta", "Hollis", "Ines", "Jovan",
    "Kaia", "Leander", "Mireille", "Nikolai", "Odessa", "Pavel", "Quinn", "Rosalind", "Soren", "Talia",
    "Ulric", "Vesna", "Wren", "Xavi", "Yara", "Zev", "Anouk", "Bram", "Cleo", "Desmond",
    "Esme", "Fabian", "Galen", "Hester", "Isak", "Juno", "Kestrel", "Lior", "Maren", "Niall",
)
LAST_NAMES = (
    "Brackwater", "Calderwick", "Dovecote", "Emberly", "Fennimore", "Glasswell", "Hawksmere", "Inchbold",
    "Juniper-Rowe", "Kestrelby", "Larkspur", "Mossgrave", "Nettlefold", "Orrinwood", "Pellucid", "Quillon",
    "Rookhaven", "Sablewood", "Tamberlin", "Umberfield", "Vellacott", "Wexcombe", "Yarrowby", "Zephyrine",
    "Ashcombe", "Birchley", "Coldharbour", "Driftwood", "Eastholm", "Foxbury", "Greywater", "Hollowell",
    "Ivybridge-Lane", "Jarrowmere", "Kingsbarrow", "Lindqvane", "Marrowby", "Northfleet", "Oldcastle-Pym",
    "Pennyrigg",
)


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: str  # vp | director | lead | engineer
    team: str | None  # None for the VP and directors (leadership sits above teams)
    manager: str | None
    valid_to: int | None  # None = still here

    @property
    def active(self) -> bool:
        return self.valid_to is None

    def active_at(self, t: int) -> bool:
        return self.valid_to is None or t < self.valid_to


@dataclass(frozen=True)
class OnCall:
    person: str
    team: str
    from_ms: int
    to_ms: int
    key: str


@dataclass(frozen=True)
class Ownership:
    team: str
    component: str
    from_ms: int
    to_ms: int | None  # None = current
    key: str


@dataclass
class Org:
    seed: int
    people: list[Person]
    teams: list[tuple[str, str]]
    members: dict[str, list[str]]  # team -> [lead, engineers…] (ids, deterministic order)
    components: dict[str, str]  # component id -> label (Service | Datastore | Transform | KPI)
    ownership: list[Ownership]
    rota: list[OnCall]
    collaborates: list[tuple[str, str, float]]  # (a, b, w) with a < b
    _by_id: dict[str, Person] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {p.id: p for p in self.people}

    def person(self, pid: str) -> Person:
        return self._by_id[pid]

    def owner_at(self, component: str, t: int) -> str:
        for o in self.ownership:
            if o.component == component and o.from_ms <= t and (o.to_ms is None or t < o.to_ms):
                return o.team
        raise KeyError(f"no owner for {component} at {t}")

    def current_owner(self, component: str) -> str:
        return next(o.team for o in self.ownership if o.component == component and o.to_ms is None)

    def on_call_at(self, team: str, t: int) -> str | None:
        for r in self.rota:
            if r.team == team and r.from_ms <= t < r.to_ms:
                return r.person
        return None

    def lead_of(self, team: str) -> str:
        return self.members[team][0]


def load_topology(path: Path = TOPOLOGY_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def data_components(lineage_dir: Path = LINEAGE_DIR) -> tuple[list[str], list[str]]:
    """Transform and KPI ids from the lineage fixture when it exists, else the documented defaults."""
    transforms, kpis = list(DEFAULT_TRANSFORMS), list(DEFAULT_KPIS)
    tf, kf = lineage_dir / "transforms.json", lineage_dir / "kpis.json"
    if tf.exists():
        transforms = sorted(str(t["id"]) for t in json.loads(tf.read_text()))
    if kf.exists():
        kpis = sorted(str(k["id"]) for k in json.loads(kf.read_text()))
    return transforms, kpis


def _components(topo: dict) -> dict[str, str]:
    comps: dict[str, str] = {}
    for s in topo["services"]:
        comps[s["id"]] = "Service"
    for d in topo["datastores"]:
        comps[d["id"]] = "Datastore"
    transforms, kpis = data_components()
    for t in transforms:
        comps[t] = "Transform"
    for k in kpis:
        comps[k] = "KPI"
    return comps


def _current_owners(comps: dict[str, str]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for team, owned in TEAM_OWNS.items():
        for c in owned:
            if c in owners:
                raise ValueError(f"{c} owned by both {owners[c]} and {team}")
            owners[c] = team
    for c, label in comps.items():
        if label in ("Transform", "KPI"):
            owners[c] = DATA_TEAM
    missing = [c for c in comps if c not in owners]
    unknown = [c for c in owners if c not in comps]
    if missing or unknown:
        raise ValueError(f"ownership map out of sync with topology: missing={missing} unknown={unknown}")
    return owners


def _people(rng: random.Random) -> tuple[list[Person], dict[str, list[str]]]:
    if sum(ENGINEERS_PER_TEAM.values()) + len(TEAMS) + 3 != N_PEOPLE:
        raise ValueError("team sizes do not add up to N_PEOPLE")
    ids = [f"p-{i:03d}" for i in range(1, N_PEOPLE + 1)]
    surnames = list(LAST_NAMES)
    rng.shuffle(surnames)
    names = {pid: f"{FIRST_NAMES[i]} {surnames[i]}" for i, pid in enumerate(ids)}

    vp, directors = ids[0], ids[1:3]
    team_ids = [t for t, _ in TEAMS]
    leads = dict(zip(team_ids, ids[3:3 + len(TEAMS)]))
    engineers = ids[3 + len(TEAMS):]
    rng.shuffle(engineers)
    members: dict[str, list[str]] = {}
    cursor = 0
    for t in team_ids:
        n = ENGINEERS_PER_TEAM[t]
        members[t] = [leads[t], *sorted(engineers[cursor:cursor + n])]
        cursor += n

    # Inactive engineers: one from INACTIVE_REQUIRED_TEAM (left recently), the rest from distinct
    # other teams, so every team keeps at least three active members for the rota.
    others = [t for t in team_ids if t != INACTIVE_REQUIRED_TEAM]
    leaving_teams = [INACTIVE_REQUIRED_TEAM, *rng.sample(others, N_INACTIVE - 1)]
    valid_to: dict[str, int] = {}
    for i, t in enumerate(leaving_teams):
        pid = rng.choice(members[t][1:])
        days_ago = INACTIVE_REQUIRED_DAYS_AGO if i == 0 else rng.randint(20, 100)
        valid_to[pid] = ANCHOR_MS - days_ago * DAY_MS + 17 * HOUR_MS

    director_of = {t: directors[i] for i, ts in enumerate(DIRECTOR_TEAMS) for t in ts}
    people = [Person(vp, names[vp], "vp", None, None, None)]
    people += [Person(d, names[d], "director", None, vp, None) for d in directors]
    for t in team_ids:
        lead, *engs = members[t]
        people.append(Person(lead, names[lead], "lead", t, director_of[t], None))
        people += [Person(e, names[e], "engineer", t, lead, valid_to.get(e)) for e in engs]
    people.sort(key=lambda p: p.id)
    return people, members


def _ownership(owners: dict[str, str]) -> list[Ownership]:
    changes = {c: (old, new, ANCHOR_MS - days * DAY_MS) for c, old, new, days in OWNERSHIP_CHANGES}
    out: list[Ownership] = []
    for c in sorted(owners):
        if c in changes:
            old, new, at = changes[c]
            if owners[c] != new:
                raise ValueError(f"ownership change for {c} must end at its current owner {owners[c]}")
            out.append(Ownership(old, c, ORG_EPOCH_MS, at, str(ORG_EPOCH_MS)))
            out.append(Ownership(new, c, at, None, str(at)))
        else:
            out.append(Ownership(owners[c], c, ORG_EPOCH_MS, None, str(ORG_EPOCH_MS)))
    return out


def _rota(people: dict[str, Person], members: dict[str, list[str]]) -> list[OnCall]:
    """Weekly rota per team: contiguous, non-overlapping, and nobody on call after they left."""
    out: list[OnCall] = []
    for t, _ in TEAMS:
        pool = members[t]
        cursor, start, w = 0, ROTA_START_MS, 0
        while start < ROTA_END_MS:
            end = min(start + WEEK_MS, ROTA_END_MS)
            for _ in range(len(pool)):
                cand = people[pool[cursor % len(pool)]]
                cursor += 1
                if cand.valid_to is None or cand.valid_to >= end:
                    out.append(OnCall(cand.id, t, start, end, f"w{w:02d}"))
                    break
            else:
                raise ValueError(f"team {t} has nobody to put on call for week {w}")
            start, w = end, w + 1
    return out


def _collaborates(rng: random.Random, people: list[Person], members: dict[str, list[str]]) -> list[tuple[str, str, float]]:
    pairs: dict[tuple[str, str], float] = {}

    def add(a: str, b: str, w: float) -> None:
        key = (a, b) if a < b else (b, a)
        if a != b and key not in pairs:
            pairs[key] = round(w, 2)

    for t, _ in TEAMS:
        team = members[t]
        for i, a in enumerate(team):
            for b in team[i + 1:]:
                add(a, b, rng.uniform(0.55, 1.0))
    by_role = {r: [p for p in people if p.role == r] for r in ("vp", "director", "lead")}
    for p in by_role["lead"] + by_role["director"]:
        add(p.id, p.manager or "", rng.uniform(0.6, 0.85))
    add(by_role["director"][0].id, by_role["director"][1].id, 0.7)
    engineers = [p.id for p in people if p.role == "engineer"]
    team_of = {p.id: p.team for p in people}
    cross = 0
    while cross < 24:
        a, b = rng.sample(engineers, 2)
        key = (a, b) if a < b else (b, a)
        if team_of[a] != team_of[b] and key not in pairs:
            add(a, b, rng.uniform(0.1, 0.45))
            cross += 1
    return [(a, b, w) for (a, b), w in sorted(pairs.items())]


def generate(seed: int = 42) -> Org:
    rng = random.Random(seed)
    topo = load_topology()
    comps = _components(topo)
    owners = _current_owners(comps)
    people, members = _people(rng)
    by_id = {p.id: p for p in people}
    return Org(
        seed=seed,
        people=people,
        teams=list(TEAMS),
        members=members,
        components=comps,
        ownership=_ownership(owners),
        rota=_rota(by_id, members),
        collaborates=_collaborates(rng, people, members),
    )


def org_to_bundle(org: Org) -> Bundle:
    b = Bundle()
    for tid, name in org.teams:
        b.node("Team", team_node_id(tid), tenant=TENANT, name=name, key=tid)
    for p in org.people:
        props: dict = {"tenant": TENANT, "name": p.name, "role": p.role, "active": p.active}
        if p.valid_to is not None:
            props["valid_to"] = p.valid_to
        b.node("Person", p.id, **props)
        if p.team is not None:
            member = {"from": ORG_EPOCH_MS}
            if p.valid_to is not None:
                member["to"] = p.valid_to
            b.edge("MEMBER_OF", "Person", p.id, "Team", team_node_id(p.team), **member)
        if p.manager is not None:
            b.edge("REPORTS_TO", "Person", p.id, "Person", p.manager, **{"from": ORG_EPOCH_MS})
    for r in org.rota:
        b.edge("ON_CALL", "Person", r.person, "Team", team_node_id(r.team), **{"from": r.from_ms, "to": r.to_ms, "key": r.key})
    for a, c, w in org.collaborates:
        b.edge("COLLABORATES", "Person", a, "Person", c, w=w)
        b.edge("COLLABORATES", "Person", c, "Person", a, w=w)
    for o in org.ownership:
        label = org.components[o.component]
        if o.to_ms is None:
            b.edge("OWNS", "Team", team_node_id(o.team), label, o.component, **{"from": o.from_ms})
        hist = {"from": o.from_ms, "key": o.key}
        if o.to_ms is not None:
            hist["to"] = o.to_ms
        b.edge("OWNED_AT", "Team", team_node_id(o.team), label, o.component, **hist)
    return b


def build(seed: int = 42) -> Bundle:
    return org_to_bundle(generate(seed))
