"""globex organisation → Bundle (same shapes as `ingest/org_gen.py`; reuses its Person/OnCall/Ownership/Org model).

12 teams (one per domain, `team-<key>`), 180 people (`gx-p-001` …): one VP, three directors, a lead per team and
engineers spread over the teams; 10% have left (`active=false`, `valid_to`), including the departed sole expert
of one component. Weekly ON_CALL rota per team over [ROTA_START_MS, ROTA_END_MS) that never schedules someone
after they left. COLLABORATES {w} is symmetric (one edge each way). OWNS = current owner (none for orphaned
components); OWNED_AT {from, to?, key} = every ownership period.
"""

from __future__ import annotations

import random
from functools import lru_cache

from ..bundle import Bundle
from ..clock import ANCHOR_MS, DAY_MS, HOUR_MS, ORG_EPOCH_MS, ROTA_END_MS, ROTA_START_MS, WEEK_MS
from ..org_gen import OnCall, Org, Ownership, Person, team_node_id
from . import TENANT, load_spec, topology

SEED_SALT = 104_729

FIRST_NAMES = (
    "Aurelio", "Brisa", "Caspian", "Delphine", "Eamon", "Fenna", "Gideon", "Halcyon", "Ilse", "Joaquim",
    "Katriel", "Linnea", "Matthias", "Noor", "Orla", "Peregrine", "Quintessa", "Rafferty", "Sunniva", "Tobiah",
    "Ulla", "Valentin", "Wilhelmina", "Ximena", "Yusuf", "Zinnia", "Anselm", "Bronwen", "Cosima", "Darius",
    "Eulalie", "Fintan", "Gwendolyn", "Hamish", "Isadora", "Jasper",
)
LAST_NAMES = (
    "Ashgrove", "Bellweather", "Cinderford", "Dunmore", "Elderwood", "Farthingale", "Gladstone-Rye", "Harrowgate",
    "Ironwood", "Jessamine", "Kilbride", "Loxley", "Merriweather", "Nightingale", "Ottershaw", "Pemberton",
    "Quarrington", "Ravenscroft", "Stonebridge", "Thistlewood", "Underhill", "Valemont", "Whitlock", "Yarborough",
    "Zellweger", "Abernethy", "Blackthorne", "Cresswell", "Drummond", "Edgecombe", "Fairbairn", "Greenhalgh",
    "Hollingsworth", "Inglewood", "Kingsley-Vane", "Lockhart",
)


class GlobexOrg(Org):
    """Org with orphaned components: their last owning team still answers for history (authorship, repo home),
    but there is no current OWNS edge."""

    def owner_at(self, component: str, t: int) -> str:
        best: Ownership | None = None
        for o in self.ownership:
            if o.component != component or o.from_ms > t:
                continue
            if o.to_ms is None or t < o.to_ms:
                return o.team
            if best is None or (o.to_ms or 0) > (best.to_ms or 0):
                best = o
        if best is None:
            raise KeyError(f"no owner for {component} at {t}")
        return best.team

    def current_owner(self, component: str) -> str:
        return self.owner_at(component, ANCHOR_MS)

    def is_orphan(self, component: str) -> bool:
        return not any(o.component == component and o.to_ms is None for o in self.ownership)


def person_id(n: int) -> str:
    return f"gx-p-{n:03d}"


def _people(spec: dict, rng: random.Random) -> tuple[list[Person], dict[str, list[str]]]:
    cfg = spec["org"]
    teams = [d["key"] for d in spec["domains"]]
    n_people, n_dir = int(cfg["people"]), len(cfg["directors"])
    ids = [person_id(i) for i in range(1, n_people + 1)]
    combos = [(f, s) for f in FIRST_NAMES for s in LAST_NAMES]
    names = {pid: f"{f} {s}" for pid, (f, s) in zip(ids, rng.sample(combos, n_people))}

    vp, directors = ids[0], ids[1:1 + n_dir]
    leads = dict(zip(teams, ids[1 + n_dir:1 + n_dir + len(teams)]))
    engineers = ids[1 + n_dir + len(teams):]
    rng.shuffle(engineers)
    base, extra = divmod(len(engineers), len(teams))
    members: dict[str, list[str]] = {}
    cursor = 0
    for i, t in enumerate(teams):
        n = base + (1 if i < extra else 0)
        members[t] = [leads[t], *sorted(engineers[cursor:cursor + n])]
        cursor += n

    # Inactive engineers: the departed expert first, then the rest spread over teams (≤ 2 per team).
    dep = cfg["departed_expert"]
    valid_to: dict[str, int] = {}
    expert = rng.choice(members[dep["team"]][1:])
    valid_to[expert] = ANCHOR_MS - int(dep["days"]) * DAY_MS + 17 * HOUR_MS
    per_team = {t: (1 if t == dep["team"] else 0) for t in teams}
    pool = [e for t in teams for e in members[t][1:] if e != expert]
    team_of = {e: t for t in teams for e in members[t][1:]}
    for e in rng.sample(pool, len(pool)):
        if len(valid_to) >= int(cfg["inactive"]):
            break
        if per_team[team_of[e]] >= 2:
            continue
        per_team[team_of[e]] += 1
        valid_to[e] = ANCHOR_MS - rng.randint(15, 110) * DAY_MS + rng.randint(8, 18) * HOUR_MS

    director_of = {t: directors[i] for i, ts in enumerate(cfg["directors"]) for t in ts}
    if set(director_of) != set(teams):
        raise ValueError("org.directors must cover every team exactly once")
    people = [Person(vp, names[vp], "vp", None, None, None)]
    people += [Person(d, names[d], "director", None, vp, None) for d in directors]
    for t in teams:
        lead, *engs = members[t]
        people.append(Person(lead, names[lead], "lead", t, director_of[t], None))
        people += [Person(e, names[e], "engineer", t, lead, valid_to.get(e)) for e in engs]
    people.sort(key=lambda p: p.id)
    return people, members


def _ownership(spec: dict, comps: dict[str, str], domain_of: dict[str, str]) -> list[Ownership]:
    moves = {m["component"]: m for m in spec["ownership_changes"]}
    orphans = {o["component"]: o for o in spec["orphans"]}
    out: list[Ownership] = []
    for c in sorted(comps):
        if c in moves:
            m = moves[c]
            if m["to"] != domain_of[c]:
                raise ValueError(f"ownership change for {c} must end at its domain {domain_of[c]}")
            at = ANCHOR_MS - int(m["days"]) * DAY_MS
            out.append(Ownership(m["from"], c, ORG_EPOCH_MS, at, str(ORG_EPOCH_MS)))
            out.append(Ownership(m["to"], c, at, None, str(at)))
        elif c in orphans:
            o = orphans[c]
            out.append(Ownership(o["from"], c, ORG_EPOCH_MS, ANCHOR_MS - int(o["days"]) * DAY_MS, str(ORG_EPOCH_MS)))
        else:
            out.append(Ownership(domain_of[c], c, ORG_EPOCH_MS, None, str(ORG_EPOCH_MS)))
    return out


def _rota(teams: list[str], people: dict[str, Person], members: dict[str, list[str]]) -> list[OnCall]:
    out: list[OnCall] = []
    for t in teams:
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


def _collaborates(rng: random.Random, people: list[Person], members: dict[str, list[str]],
                  teams: list[str]) -> list[tuple[str, str, float]]:
    pairs: dict[tuple[str, str], float] = {}

    def add(a: str, b: str, w: float) -> None:
        key = (a, b) if a < b else (b, a)
        if a != b and key not in pairs:
            pairs[key] = round(w, 2)

    for t in teams:
        lead, *engs = members[t]
        for e in engs:
            add(lead, e, rng.uniform(0.6, 1.0))
        for i, a in enumerate(engs):
            for b in engs[i + 1:]:
                if rng.random() < 0.4:
                    add(a, b, rng.uniform(0.5, 1.0))
    by_role = {r: [p for p in people if p.role == r] for r in ("director", "lead")}
    for p in by_role["lead"] + by_role["director"]:
        add(p.id, p.manager or "", rng.uniform(0.6, 0.85))
    ds = by_role["director"]
    for i, a in enumerate(ds):
        for b in ds[i + 1:]:
            add(a.id, b.id, 0.7)
    engineers = [p.id for p in people if p.role == "engineer"]
    team_of = {p.id: p.team for p in people}
    cross = 0
    while cross < 120:
        a, b = rng.sample(engineers, 2)
        key = (a, b) if a < b else (b, a)
        if team_of[a] != team_of[b] and key not in pairs:
            add(a, b, rng.uniform(0.1, 0.45))
            cross += 1
    return [(a, b, w) for (a, b), w in sorted(pairs.items())]


@lru_cache(maxsize=4)
def generate(seed: int = 42) -> GlobexOrg:
    spec = load_spec()
    topo = topology.generate(seed)
    rng = random.Random(seed * SEED_SALT + 3)
    teams = [(d["key"], d["name"]) for d in spec["domains"]]
    keys = [k for k, _ in teams]
    people, members = _people(spec, rng)
    by_id = {p.id: p for p in people}
    comps = topo.components()
    return GlobexOrg(
        seed=seed,
        people=people,
        teams=teams,
        members=members,
        components=comps,
        ownership=_ownership(spec, comps, topo.domain),
        rota=_rota(keys, by_id, members),
        collaborates=_collaborates(rng, people, members, keys),
    )


def build(seed: int = 42) -> Bundle:
    org = generate(seed)
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
