"""Ingest: deterministic producers of graph rows. Producers never touch FalkorDB; `scripts/seed.py`
applies their bundles through `graph/writes.py` (engine user, idempotent UNWIND … MERGE)."""
