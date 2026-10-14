import pytest

from faultline.graph import tenant


@pytest.mark.parametrize("t", ["acme", "globex", "t1"])
def test_valid_tenants(t):
    assert tenant.tenant_graph(t) == f"tenant_{t}"


@pytest.mark.parametrize("t", ["", "A", "1abc", "acme;", "acme_x", "tenant acme", "x" * 40, None])
def test_invalid_tenants_rejected(t):
    with pytest.raises(ValueError):
        tenant.tenant_graph(t)


def test_derived_graphs_are_tenant_scoped():
    assert tenant.scratch_graph("acme", "inc_abc_1") == "scratch_acme_inc_abc_1"
    assert tenant.whatif_graph("acme", "op-7").startswith("whatif_acme_")
    assert tenant.eval_graph("globex", "r1", "a3", "s1", 2) == "eval_globex_r1_a3_s1_2"
    assert tenant.eval_graph("globex", "r1", "A3", "S1", 2).startswith("eval_globex_r1_a3_s1_2_")
    assert tenant.golden_graph("acme", nomem=True) == "golden_acme_nomem"


def test_injection_in_suffix_is_neutralised():
    name = tenant.scratch_graph("acme", "x'}) DETACH DELETE n //")
    assert set(name) <= set("abcdefghijklmnopqrstuvwxyz0123456789_")


def test_sanitised_names_do_not_collide():
    assert tenant.scratch_graph("acme", "inc_ABC-1") != tenant.scratch_graph("acme", "inc_abc_1")
    a = tenant.eval_graph("acme", "r" * 70, "A3", "S1", 1)
    b = tenant.eval_graph("acme", "r" * 70, "A3", "S1", 2)
    assert a != b and len(a) <= 90


def test_graph_belongs_to():
    assert tenant.graph_belongs_to("tenant_acme", "acme")
    assert tenant.graph_belongs_to("whatif_acme_op1", "acme")
    assert not tenant.graph_belongs_to("tenant_acme2", "acme")
    assert not tenant.graph_belongs_to("scratch_globex_x", "acme")
