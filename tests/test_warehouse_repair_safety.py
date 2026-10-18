"""Warehouse sandbox and repair-scope safety."""

import pytest

from faultline import repair, warehouse


def test_repair_restricted_to_transforms():
    with pytest.raises(ValueError):
        repair.propose_patch("backend/faultline/api.py", "x", "nope")
    with pytest.raises((ValueError, FileNotFoundError)):
        repair.propose_patch("pipeline/transforms/../../Makefile", "x", "nope")


def test_propose_patch_produces_real_diff():
    current = warehouse.read_transform("stg_orders")["sql"]
    patched = current.replace("CAST(amount AS DOUBLE) AS amount", "CAST(amount AS DOUBLE) AS amount_x")
    p = repair.propose_patch("pipeline/transforms/stg_orders.sql", patched, "test")
    assert p.diff.startswith("--- a/pipeline/transforms/stg_orders.sql")
    assert "+" in p.diff and "-" in p.diff
    with pytest.raises(ValueError):
        repair.propose_patch("pipeline/transforms/stg_orders.sql", current, "identical")


# ------------------------------------------------------------ sql read-only


def test_run_sql_rejects_writes():
    with pytest.raises(ValueError):
        warehouse.run_sql("DROP TABLE staging.stg_orders")
    with pytest.raises(ValueError):
        warehouse.run_sql("SELECT 1; SELECT 2")
    assert warehouse.run_sql("SELECT 1 AS x")["rows"] == [[1]]


def test_run_sql_blocks_filesystem_exfiltration():
    # denylist layer
    with pytest.raises(ValueError):
        warehouse.run_sql("SELECT * FROM read_csv('/etc/hosts')")
    with pytest.raises(ValueError):
        warehouse.run_sql("SELECT * FROM read_text('.env')")
    # connection-hardening layer (bypass the regex with a novel function name):
    # any external-access attempt must fail at the DuckDB level too
    import duckdb as _duckdb

    with pytest.raises((_duckdb.Error, ValueError)):
        warehouse.run_sql("SELECT * FROM read_ndjson_objects('.env')")
