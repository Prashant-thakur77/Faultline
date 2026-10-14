"""Central configuration. All paths are derived from the repo root so the app
can be launched from anywhere inside the repository."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "pyproject.toml").exists() and (parent / "pipeline").exists():
            return parent
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _find_repo_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    # Exact model ids are pinned and printed in every run artefact.
    anthropic_model: str = "claude-opus-5-5"
    anthropic_specialist_model: str = "claude-sonnet-5-5"

    # FalkorDB: the only store. Engine user writes; ro_<tenant> users only RO_QUERY.
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_engine_user: str = ""          # empty = default user (local dev without ACL)
    falkordb_engine_password: str = ""
    falkordb_ro_password: str = ""          # empty = RO connection via the default user (dev; /status says so)
    falkordb_timeout_ms: int = 2000         # per-query TIMEOUT for templates
    falkordb_timeout_max_ms: int = 10000    # server TIMEOUT_MAX (configure_falkordb.py); requests are clamped to it
    falkordb_cypher_timeout_ms: int = 3000  # guarded text2cypher
    falkordb_result_limit: int = 100        # wrapper row cap (templates also carry a literal LIMIT)
    faultline_tenant: str = "acme"
    # MCP over Streamable HTTP: comma-separated "<bearer key>:<tenant>" pairs (secret; .env only)
    faultline_mcp_keys: str = ""
    faultline_mcp_rate_per_min: int = 30
    # required to approve actions when FAULTLINE_GITHUB=real (secret; .env only)
    faultline_approver_key: str = ""
    # optional bearer key for POST /api/preflight when the API is public (secret; .env only)
    faultline_preflight_key: str = ""
    # PUBLIC live demo mode: acting routes need the per-run token; destructive or recording routes work on clean-room
    # copies unless the admin key is given; the LLM needs its own key header (no anonymous spend)
    faultline_public: bool = False
    faultline_admin_key: str = ""
    faultline_llm_key: str = ""
    # salt for the re-arm audit's client-IP hash (secret; .env only). Unset: a random per-process salt, so hashes are
    # never linkable to an IP by brute force over the IPv4 space, nor across restarts
    faultline_audit_salt: str = ""
    faultline_llm_budget_usd_per_hour: float = 2.0   # live-LLM runs stop (replay only) once the last hour spent this
    faultline_llm_usd_per_mtok_in: float = 15.0      # conservative upper-bound price used to cost each run
    faultline_llm_usd_per_mtok_out: float = 75.0
    faultline_llm_reserve_usd_run: float = 0.5       # reserved on the global ledger before a live-LLM run starts (settled after)
    faultline_llm_reserve_usd_ask: float = 0.1       # reserved before a live-LLM brain question (settled after)
    faultline_cors_origins: str = "*"
    # Ablation arm A4: every graph tool raises GraphUnavailable before any network call.
    faultline_disable_graph: bool = False


    faultline_api_port: int = 8400

    # Autonomous PR publication (env FAULTLINE_CREATE_PR). OFF by default: the demo and
    # the evals must never push to a remote. When true, a VERIFIED repair additionally
    # pushes its `faultline/fix-*` branch to `origin` and opens a real PR via `gh`.
    # Failure of that step is recorded as evidence and never changes the verified outcome.
    faultline_create_pr: bool = False

    # Fixture / pipeline layout (kept in sync with pipeline/)
    warehouse_path: Path = REPO_ROOT / "data" / "warehouse" / "faultline.duckdb"
    metric_snapshot_path: Path = REPO_ROOT / "data" / "warehouse" / "metric_snapshot.json"
    transforms_dir: Path = REPO_ROOT / "pipeline" / "transforms"
    # pristine, hash-pinned copies of the transforms (repair.restore_pristine; review round 5, M3)
    transforms_pristine_dir: Path = REPO_ROOT / "pipeline" / "transforms_pristine"
    sources_dir: Path = REPO_ROOT / "data" / "sources"
    baselines_dir: Path = REPO_ROOT / "pipeline" / "baselines"
    incidents_dir: Path = REPO_ROOT / "data" / "incidents"



settings = Settings()
