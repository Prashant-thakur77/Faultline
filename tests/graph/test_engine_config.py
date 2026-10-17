"""M20 #2 (unit): the per-query memory cap is configured in one place (weights.yaml) and reaches both the runtime config
(scripts/configure_falkordb.py) and the engine's load-time args (deploy/docker-compose.yml FALKORDB_ARGS, which a
restart without configure keeps); the RO wrapper maps the engine's cap error to GraphMemoryCapExceeded (fail closed)."""

import importlib.util
import re
from pathlib import Path

import yaml

from faultline.agent.weights import weights
from faultline.graph.errors import GraphMemoryCapExceeded
from faultline.graph.ro import classify

ROOT = Path(__file__).resolve().parents[2]


class _ComposeLoader(yaml.SafeLoader):
    """Compose files use the `!reset` / `!override` merge tags; read them as plain values."""


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, lambda loader, node: loader.construct_sequence(node)
                                   if isinstance(node, yaml.SequenceNode) else loader.construct_scalar(node)
                                   if isinstance(node, yaml.ScalarNode) else loader.construct_mapping(node))


def compose(name: str) -> dict:
    return yaml.load((ROOT / "deploy" / name).read_text(), Loader=_ComposeLoader)


def _configure():
    spec = importlib.util.spec_from_file_location("configure_falkordb", ROOT / "scripts" / "configure_falkordb.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_mem_cap_from_weights_reaches_runtime_config_and_compose():
    want = int(weights()["engine"]["query_mem_capacity_mb"]) * 1024 * 1024
    assert want > 0
    assert _configure().config()["QUERY_MEM_CAPACITY"] == want
    args = compose("docker-compose.yml")["services"]["falkordb"]["environment"]["FALKORDB_ARGS"]
    m = re.search(r"\bQUERY_MEM_CAPACITY\s+(\d+)\b", args)
    assert m and int(m.group(1)) == want, args
    prod = compose("docker-compose.prod.yml")["services"]["falkordb"]
    assert "FALKORDB_ARGS" not in (prod.get("environment") or {})       # prod inherits the base args (same cap)


def test_engine_cap_error_is_its_own_loud_error():
    e = classify(Exception("Query's mem consumption exceeded capacity"), "T2C")
    assert isinstance(e, GraphMemoryCapExceeded) and "QUERY_MEM_CAPACITY" in str(e)


def test_prod_engine_has_no_internet_route():
    """M20 #9: FalkorDB only on the internal `engine` network; api and mcp on engine + default (GitHub, Telegram);
    ui and caddy never on the engine network; nothing published from the engine."""
    prod = compose("docker-compose.prod.yml")
    assert prod["networks"]["engine"]["internal"] is True
    svc = prod["services"]
    assert svc["falkordb"]["networks"] == ["engine"] and svc["falkordb"]["ports"] == []
    for s in ("api", "mcp"):
        assert set(svc[s]["networks"]) == {"engine", "default"}
    for s in ("ui", "caddy"):
        assert "engine" not in (svc[s].get("networks") or [])
