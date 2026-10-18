"""CI lint: FalkorDB is the only store.

Fails on, inside backend/faultline:
  * imports of other stores / graph libraries: sqlite3, sqlalchemy, networkx, chromadb, lancedb,
    qdrant_client, pinecone (duckdb only in warehouse.py, the system under observation);
  * runtime state read from JSON (`json.load(` / `json.loads(<file>.read_text())`) in agent/,
    actions/, memory/, brain/, preflight/, mcp_server/ and store.py;
  * hand-written graph algorithms: `deque(` or functions named like bfs/dfs/dijkstra/shortest_path/
    pagerank/betweenness/centrality/downstream_of/upstream_of/traverse;
  * Cypher built with f-strings or `.format(` near MATCH/MERGE/CREATE/CALL outside graph/.
Known, sanctioned exceptions are listed in scripts/single_store_allowlist.txt with a reason and the
milestone that removes them; the list must shrink to the sanctioned entries by the end of M2.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "backend" / "faultline"
ALLOWLIST = ROOT / "scripts" / "single_store_allowlist.txt"

BANNED_IMPORTS = {"sqlite3", "sqlalchemy", "networkx", "chromadb", "lancedb", "qdrant_client", "pinecone",
                  "psycopg2", "psycopg", "pymongo", "pickle", "shelve", "dbm", "sklearn", "faiss", "annoy", "hnswlib",
                  "igraph", "graph_tool", "rustworkx", "sentence_transformers"}
STATE_ONLY_BANNED = {"numpy", "scipy", "yaml"}  # no vector maths / runtime YAML state in decision paths
TRAVERSAL_IMPORTS = {("collections", "deque"), ("heapq", None)}
STATE_DIRS = ("agent", "actions", "memory", "brain", "preflight", "mcp_server")
ALGO_NAME = re.compile(r"(^|_)(bfs|dfs|dijkstra|shortest_path|pagerank|betweenness|centrality|downstream_of|upstream_of|traverse)(_|$)", re.I)
CYPHER_FSTR = re.compile(r"\b(MATCH|MERGE|CREATE|CALL|DETACH|UNWIND)\b")


def _cypherish(text: str) -> bool:
    return bool(CYPHER_FSTR.search(text) and re.search(r"[(:\[]", text) and re.search(r"\b(RETURN|SET|DELETE|YIELD|WHERE)\b|\)-\[|\]->", text))


def load_allowlist() -> set[str]:
    out: set[str] = set()
    if ALLOWLIST.exists():
        for line in ALLOWLIST.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line.split("|", 1)[0].strip())
    return out


def check_file(path: Path, rel: str) -> list[tuple[str, str]]:
    """Return [(key, message)]; key = 'rel' or 'rel::symbol' for allowlisting."""
    problems: list[tuple[str, str]] = []
    try:
        tree = ast.parse(path.read_text(), filename=rel)
    except SyntaxError as e:
        return [(rel, f"syntax error: {e}")]
    in_state_dir = rel.split("/")[0] in STATE_DIRS or rel == "store.py"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if isinstance(node, ast.ImportFrom) and in_state_dir and (node.module or "") == "json":
                if any(a.name in ("load", "loads") for a in node.names):
                    problems.append((rel, f"{rel}:{node.lineno} from json import load (runtime state from JSON)"))
            for mod_name, member in TRAVERSAL_IMPORTS:
                if isinstance(node, ast.ImportFrom) and node.module == mod_name and (member is None or any(a.name == member for a in node.names)):
                    problems.append((f"{rel}::import-{member or mod_name}", f"{rel}:{node.lineno} imports {mod_name}.{member or ''} (graph traversal in Python?)"))
                if isinstance(node, ast.Import) and member is None and any(a.name == mod_name for a in node.names):
                    problems.append((f"{rel}::import-{mod_name}", f"{rel}:{node.lineno} imports {mod_name} (graph traversal in Python?)"))
            for m in mods:
                top = m.split(".")[0]
                if top in STATE_ONLY_BANNED and in_state_dir:
                    problems.append((f"{rel}::import-{top}", f"{rel}:{node.lineno} imports {top} in a decision path"))
                if top in BANNED_IMPORTS:
                    local = isinstance(node, ast.ImportFrom) and node.level > 0
                    key = f"{rel}::import-{top}" if local else rel
                    problems.append((key, f"{rel}:{node.lineno} imports {m} (another store/graph library)"))
                if top == "duckdb" and rel != "warehouse.py":
                    problems.append((rel, f"{rel}:{node.lineno} imports duckdb outside warehouse.py"))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ALGO_NAME.search(node.name):
            problems.append((f"{rel}::{node.name}", f"{rel}:{node.lineno} hand-written graph routine {node.name}()"))
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "deque":
                problems.append((rel, f"{rel}:{node.lineno} deque() (graph traversal in Python?)"))
            if in_state_dir and name in ("load", "loads") and isinstance(fn, ast.Attribute) and getattr(fn.value, "id", "") == "json":
                arg = ast.unparse(node.args[0]) if node.args else ""
                reads_file = name == "load" or "read_text" in arg or "open(" in arg or "read_bytes" in arg
                if reads_file:  # json.loads of a property returned by FalkorDB is fine; state from files is not
                    problems.append((rel, f"{rel}:{node.lineno} json.{name}() of runtime state from a file"))
        if isinstance(node, (ast.While,)):
            src = ast.unparse(node)
            if re.search(r"\.pop\(0\)|\.popleft\(\)", src):
                problems.append((f"{rel}::traversal-loop", f"{rel}:{node.lineno} queue-based loop (graph traversal in Python?)"))
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if _cypherish(text):
                problems.append((f"{rel}::fstring-cypher", f"{rel}:{node.lineno} Cypher built with an f-string"))
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str) and _cypherish(side.value):
                    problems.append((f"{rel}::concat-cypher", f"{rel}:{node.lineno} Cypher built with + or %"))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
                and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)
                and _cypherish(node.func.value.value)):
            problems.append((f"{rel}::format-cypher", f"{rel}:{node.lineno} Cypher built with .format()"))
    return problems


EVALS = ROOT / "evals"
WRITE_KW = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE)\b")


def check_evals() -> list[str]:
    """Evals run on fresh GRAPH.COPY clean rooms and write only through the product (graph/writes.py): no raw write
    Cypher in evals/ (a raw DETACH DELETE on a shared tenant graph is how a clean room gets skipped)."""
    out = []
    for path in sorted(EVALS.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "query"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and WRITE_KW.search(node.args[0].value)):
                out.append(f"{path.relative_to(ROOT)}:{node.lineno}: raw write Cypher in an eval; use a clean room + writes.py")
    return out


def main(paths: list[str] | None = None) -> int:
    root = Path(paths[0]) if paths else PKG
    allow = load_allowlist()
    found: list[str] = []
    allowed_hits: set[str] = set()
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("graph/smoke/"):
            continue
        for key, msg in check_file(p, rel):
            file_key = key.split("::", 1)[0]
            if key in allow or file_key in allow or any(file_key.startswith(a.rstrip("*")) for a in allow if a.endswith("*")):
                allowed_hits.add(key)
                continue
            found.append(msg)
    if not paths:
        found += check_evals()
    if found:
        print("single-store lint FAILED:\n  " + "\n  ".join(found))
        return 1
    print(f"single-store lint PASS ({len(allowed_hits)} allowlisted, sanctioned hits)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
