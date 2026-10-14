"""Every node id is unique across labels (templates look nodes up by :Node {id}), e.g. a Team may
never share an id with a Service."""

from collections import Counter

from faultline.ingest import baselines, cross_domain, docs, history, lineage_to_graph, obligations, org_gen, otel_topology


def test_ids_unique_across_all_producers():
    ids = Counter()
    for m in (lineage_to_graph, otel_topology, cross_domain, baselines, org_gen, obligations, history, docs):
        for rows in m.build().nodes.values():
            ids.update(r["id"] for r in rows)
    dupes = {i: c for i, c in ids.items() if c > 1}
    assert not dupes, f"ids shared across labels/producers: {sorted(dupes)[:20]}"


def test_globex_ids_unique_across_all_producers():
    from faultline.ingest.globex import docs as gdocs, embeddings as gemb, history as ghist, obligations as gobl, org as gorg, topology as gtopo

    ids = Counter()
    for m in (gtopo, gorg, gobl, ghist, gdocs):
        for rows in m.build().nodes.values():
            ids.update(r["id"] for r in rows)
    dupes = {i: c for i, c in ids.items() if c > 1}
    assert not dupes, f"globex ids shared across labels/producers: {sorted(dupes)[:20]}"
    vec_ids = {r["id"] for rows in gemb.build().nodes.values() for r in rows}
    assert vec_ids <= set(ids), "embeddings for nodes that globex does not create"
