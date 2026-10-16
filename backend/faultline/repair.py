"""Repair engine: applies LLM-planned fixes as real file changes, verifies them by
re-executing the pipeline + invariant suite, and produces a real git artifact
(optionally published as a real GitHub pull request).

The LLM proposes the full new content of a transform; the diff is computed
deterministically here (difflib), so the displayed patch is always the patch
that actually ran. Likewise the PR body is rendered from the recorded
IncidentState only — every number in it is a number some tool actually produced.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from .config import REPO_ROOT, settings
from .models import MetricSnapshot, ProposedPatch, TestReport
from . import warehouse

# sha256 of pipeline/transforms_pristine/SHA256SUMS: the pristine transforms cannot change without a code change
PRISTINE_DIGEST = "10088b157f9c674989fa88dd6ca777bd6c015a4d7414766ce884069bfee44e0e"
_TRANSFORM_REL = re.compile(r"^pipeline/transforms/([A-Za-z0-9_]+\.sql)$")


class SqlRejected(ValueError):
    """A proposed transform is not exactly one plain CREATE TABLE|VIEW … AS SELECT of the transform's own target."""


class PristineMismatch(RuntimeError):
    """The pristine transform copies do not match their pinned digests: refuse to restore from them (fail loudly)."""


def _resolve_transform(file_rel: str) -> Path:
    """Only an existing allowlisted transform, addressed as pipeline/transforms/<name>.sql (no traversal)."""
    m = _TRANSFORM_REL.fullmatch(str(file_rel))
    if not m:
        raise ValueError(f"repairs may only modify pipeline transforms, got {file_rel!r}")
    path = settings.transforms_dir / m.group(1)
    if not path.exists():
        raise FileNotFoundError(file_rel)
    return path


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory and os.replace: a reader (or a crash) sees the old content or
    the new one, never half of it."""
    tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        with tmp.open("w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------ SQL validation (review round 5, M4)
_DENY_KEYWORDS = re.compile(
    r"\b(COPY|ATTACH|DETACH|INSTALL|LOAD|PRAGMA|SET|RESET|CALL|EXPORT|IMPORT|CHECKPOINT|VACUUM|SECRET|MACRO|FUNCTION|"
    r"EXTENSION|INSERT|UPDATE|DELETE|DROP|ALTER|GRANT|USE|PREPARE|EXECUTE|TRUNCATE)\b", re.I)
_DENY_FUNCS = re.compile(
    r"\b(read_\w+|\w+_scan|getenv|getvariable|glob|sniff_csv|query|query_table|current_setting|duckdb_\w+|"
    r"which_secret|load_extension|write_\w+|http_\w+|sqlite_\w+|postgres_\w+|mysql_\w+|iceberg_\w+|delta_\w+|"
    r"parquet_\w+|json_execute_serialized_sql|from_json\w*)\s*\(", re.I)
_CTAS = re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW)\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)\s+AS\s*\(?\s*(SELECT|WITH)\b",
                   re.I | re.S)


def _code_only(sql: str) -> str:
    """The SQL with comments removed and string-literal contents blanked (quotes kept), for the checks below."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:  # doubled quote: an escaped quote inside the literal
                        j += 2
                        continue
                    break
                j += 1
            out.append(c + " " * max(0, j - i - 1) + (c if j < n else ""))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _target_of(sql: str) -> tuple[str, str] | None:
    m = _CTAS.match(_code_only(sql))
    return (m.group(1).upper(), m.group(2).lower()) if m else None


def validate_transform_sql(file_rel: str, sql: str) -> None:
    """Accept exactly one `CREATE [OR REPLACE] TABLE|VIEW <the file's own target> AS SELECT|WITH …` and nothing that
    can reach outside the database: no COPY / ATTACH / INSTALL / LOAD / PRAGMA / SET / CALL / EXPORT / IMPORT, no
    file, network or environment functions (read_*, *_scan, glob, getenv, …), no file name as a table (FROM '…'),
    no quoted identifiers. Parsed by DuckDB itself (duckdb.extract_statements). SqlRejected otherwise. The build also
    runs with external access off and the configuration locked (pipeline/run.py), so this is the first of two layers."""
    try:
        kinds = warehouse.statement_types(sql)
    except ValueError as e:
        raise SqlRejected(f"the proposed SQL does not parse: {e}") from None
    if len(kinds) != 1:
        raise SqlRejected(f"exactly one statement is allowed (got {len(kinds)})")
    if kinds[0] != "CREATE":
        raise SqlRejected(f"only CREATE TABLE|VIEW … AS SELECT is allowed (got {kinds[0]})")
    code = _code_only(sql)
    target = _target_of(sql)
    if target is None:
        raise SqlRejected("only CREATE [OR REPLACE] TABLE|VIEW <schema.name> AS SELECT … is allowed")
    pristine = settings.transforms_pristine_dir / Path(file_rel).name
    if pristine.exists():
        own = _target_of(pristine.read_text())
        if own is not None and target[1] != own[1]:
            raise SqlRejected(f"{file_rel} builds {own[1]}; the proposal builds {target[1]}")
    kw = _DENY_KEYWORDS.search(code)
    if kw:
        raise SqlRejected(f"{kw.group(1).upper()} is not allowed in a transform")
    fn = _DENY_FUNCS.search(code)
    if fn:
        raise SqlRejected(f"{fn.group(1)}() is not allowed in a transform (file, network or environment access)")
    if re.search(r"\b(FROM|JOIN)\s*\(?\s*'", code, re.I):
        raise SqlRejected("a file name cannot be used as a table (FROM '…')")
    if '"' in code:
        raise SqlRejected("quoted identifiers are not allowed in a transform")


def propose_patch(file_rel: str, new_content: str, reasoning: str) -> ProposedPatch:
    path = _resolve_transform(file_rel)
    old = path.read_text()
    if not new_content.endswith("\n"):
        new_content += "\n"
    validate_transform_sql(file_rel, new_content)
    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{file_rel}",
            tofile=f"b/{file_rel}",
        )
    )
    if not diff:
        raise ValueError("proposed content is identical to the current file")
    return ProposedPatch(file=file_rel, diff=diff, reasoning=reasoning, status="proposed")


def _backup_of(path: Path, patch: ProposedPatch) -> Path:
    """One backup per patch (named by the patch's diff digest), never a shared `.orig` an older patch left behind."""
    return path.with_name(f"{path.name}.{hashlib.sha256(patch.diff.encode()).hexdigest()[:12]}.orig")


def apply_patch(patch: ProposedPatch, new_content: str) -> None:
    path = _resolve_transform(patch.file)
    if not new_content.endswith("\n"):
        new_content += "\n"
    validate_transform_sql(patch.file, new_content)
    cur = path.read_text()
    if cur != new_content:
        _atomic_write(_backup_of(path, patch), cur)  # this patch's own backup, written fresh at apply time
        _atomic_write(path, new_content)
    patch.status = "applied"


def revert_patch(patch: ProposedPatch, *, rebuild: bool = True) -> dict | None:
    """Restore the content this patch replaced (its own backup), then rebuild the warehouse from it (the warehouse
    was built with the patch). Fails loudly when the backup is missing: never guess how to restore a transform."""
    path = _resolve_transform(patch.file)
    backup = _backup_of(path, patch)
    if not backup.exists():
        raise FileNotFoundError(f"no backup of this patch for {patch.file}; cannot revert safely (restore it by hand)")
    _atomic_write(path, backup.read_text())
    backup.unlink()
    patch.status = "rejected"
    return warehouse.rebuild_warehouse() if rebuild else None


def revert_to(file_rel: str, *, before: str, after: str, rebuild: bool = True) -> dict:
    """A data repair that did not take: put back `before` (the approved plan's own record of the file) when the file
    still holds `after`, atomically, drop the patch's backups, and rebuild. A file that holds neither is left alone and
    reported (someone changed it since; never overwrite that)."""
    path = _resolve_transform(file_rel)
    cur = path.read_text()
    if cur == before:
        state = "already-before"
    elif cur == after:
        _atomic_write(path, before)
        state = "reverted"
    else:
        return {"state": "changed-elsewhere", "rebuilt": False}
    for b in path.parent.glob(f"{path.name}.*.orig"):
        b.unlink(missing_ok=True)
    unverified_marker(path).unlink(missing_ok=True)
    out: dict = {"state": state, "rebuilt": False}
    if rebuild and state == "reverted":
        b = warehouse.rebuild_warehouse()
        out.update(rebuilt=bool(b["ok"]), rebuild_error=None if b["ok"] else b["stderr"][:300])
    return out


def cleanup_backups() -> None:
    for p in settings.transforms_dir.glob("*.orig"):
        p.unlink()


def unverified_marker(path: Path) -> Path:
    return path.with_name(f"{path.name}.unverified.json")


def mark_unverified(file_rel: str, info: dict) -> None:
    """A data repair left applied with verdict UNKNOWN (review round 5, M3; chosen over reverting it): the patch stays
    so the reconciler can re-verify it by its idempotency key, and this marker next to the transform says whose
    unverified patch it is. The next mode switch or re-arm restores the pristine transform and removes the marker."""
    path = _resolve_transform(file_rel)
    _atomic_write(unverified_marker(path), json.dumps(info, sort_keys=True, default=str) + "\n")


def _pristine_files() -> dict[str, Path]:
    """The pristine copies, checked against SHA256SUMS and SHA256SUMS against the pinned PRISTINE_DIGEST."""
    d = settings.transforms_pristine_dir
    sums = d / "SHA256SUMS"
    if not sums.exists():
        raise PristineMismatch(f"{sums} is missing")
    raw = sums.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRISTINE_DIGEST:
        raise PristineMismatch("pipeline/transforms_pristine/SHA256SUMS does not match repair.PRISTINE_DIGEST")
    out: dict[str, Path] = {}
    for line in raw.decode().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip("*")
        f = d / name
        if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            raise PristineMismatch(f"pristine copy {name} is missing or does not match SHA256SUMS")
        out[name] = f
    return out


def restore_pristine() -> list[str]:
    """Put every transform back to its pristine copy (atomic writes), drop every patch backup and unverified marker.
    Returns the transforms that had changed. Called before every warehouse mode switch and on re-arm."""
    restored = []
    for name, src in sorted(_pristine_files().items()):
        dst = settings.transforms_dir / name
        want = src.read_text()
        if not dst.exists() or dst.read_text() != want:
            _atomic_write(dst, want)
            restored.append(name)
    for p in list(settings.transforms_dir.glob("*.orig")) + list(settings.transforms_dir.glob("*.unverified.json")):
        p.unlink(missing_ok=True)
    return restored


def verify_repair() -> tuple[TestReport, MetricSnapshot, bool]:
    """Rebuild the warehouse with the patched transform, run the full invariant
    suite, and recompute the KPI. Success = all tests pass AND KPI back in range."""
    build = warehouse.rebuild_warehouse()
    if not build["ok"]:
        report = TestReport(total=0, passed=0, failed=1, failures=[])
        snapshot = warehouse.get_metric_snapshot()
        return report, snapshot, False
    report = warehouse.run_invariants()
    snapshot = warehouse.get_metric_snapshot()
    metric_ok = 0.8 <= snapshot.anomaly_ratio <= 1.3
    return report, snapshot, report.failed == 0 and report.total > 0 and metric_ok


# ---------------------------------------------------------------------------
# Autonomous pull request
#
# Hard safety rules (see tests/test_repair_pr.py):
#   * OFF by default — settings.faultline_create_pr / FAULTLINE_CREATE_PR.
#   * Only ever runs AFTER verification succeeded; it can never gate or change it.
#   * Only branches named faultline/fix-* may be pushed, and only to `origin`.
#   * Every failure is swallowed and reported, never raised.
# ---------------------------------------------------------------------------

FIX_BRANCH_PREFIX = "faultline/fix-"
PR_TITLE_PREFIX = "fix(pipeline): "
PR_TITLE_MAX = 72


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout)


# ------------------------------------------------------------------ publish


