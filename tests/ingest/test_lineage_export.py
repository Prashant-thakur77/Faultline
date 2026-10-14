import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data/fixtures/lineage"


def test_fixture_is_complete_and_consistent():
    tables = {t["id"] for t in json.loads((ROOT / "tables.json").read_text())}
    assert len(tables) == 8
    cols = json.loads((ROOT / "columns.json").read_text())
    assert {c["table_id"] for c in cols} <= tables
    col_ids = {c["id"] for c in cols}
    for e in json.loads((ROOT / "table_lineage.json").read_text()):
        assert e["src"] in tables and e["dst"] in tables and 0 < e["cap"] <= 1
    for e in json.loads((ROOT / "column_lineage.json").read_text()):
        assert e["src"] in col_ids and e["dst"] in col_ids, e
    assert all(t.get("name") for t in json.loads((ROOT / "tables.json").read_text())), "Table.name is the full-text target"
