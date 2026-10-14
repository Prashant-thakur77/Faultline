"""G4 origin scope (agent/gate.py::origin_scope): which anomalies single out a change."""

from faultline.agent.gate import origin_scope

L = {"payment": "Service", "raw.raw_orders": "Table", "staging.stg_orders": "Table", "kpi.exec_revenue": "KPI",
     "x": "Service", "o": "Service", "frontend": "Service", "checkout": "Service", "astronomy-db": "Datastore"}


def test_service_change_counts_only_itself():
    assert origin_scope(["D1", "payment", "checkout"], ["checkout"], L) == ["payment"]


def test_data_output_of_the_changed_service_counts():  # S2: payment's error rate in band, its rows corrupt
    chain = ["D2", "payment", "raw.raw_orders", "staging.stg_orders", "kpi.exec_revenue"]
    assert origin_scope(chain, ["kpi.exec_revenue"], L) == ["payment", "raw.raw_orders", "staging.stg_orders"]


def test_bystander_upstream_of_an_unchanged_degraded_component_is_not_singled_out():
    """Review M13/M14: X (changed, healthy) → O (degraded, no change) → frontend. O's anomaly must not count for X."""
    assert origin_scope(["DX", "x", "o", "frontend"], ["frontend"], L) == ["x"]


def test_datastore_change_counts_only_itself():
    assert origin_scope(["D3", "astronomy-db", "checkout"], ["checkout"], L) == ["astronomy-db"]
