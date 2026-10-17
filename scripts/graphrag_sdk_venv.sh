#!/usr/bin/env bash
# Build the isolated venv for the eval-only GraphRAG-SDK arm (evals/graphrag_sdk_arm.py). It is never part of the
# product's dependencies: everything lives under tmp/graphrag_sdk/ (untracked).
#
#   scripts/graphrag_sdk_venv.sh            build (idempotent) and patch
#
# GraphRAG-SDK 1.4.0 creates its full-text indexes with the procedure form
# `CALL db.idx.fulltext.createNodeIndex('Chunk', 'text')`, which FalkorDB 6.0.x rejects ("Received 2 arguments to
# procedure 'db.idx.fulltext.createNodeIndex', expected at most 1"; upstream GraphRAG-SDK issue #344). The SDK logs a
# warning and carries on with no full-text index, so its full-text retrieval paths silently return nothing. The one
# local patch switches those two statements to the DDL form, which 6.0.2 accepts. Nothing else is changed.
#
# Downloads: torch (CPU build, ~200 MB) for GLiNER, the SDK's default local entity extractor, and the GLiNER model
# urchade/gliner_medium-v2.1 (~1.5 GB with its tokenizer files) into tmp/graphrag_sdk/hf.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/tmp/graphrag_sdk"
VENV="$DIR/venv"
UV="${UV:-uv}"
mkdir -p "$DIR"
if [ ! -x "$VENV/bin/python" ]; then
  "$UV" venv --python 3.12 "$VENV"
fi
"$UV" pip install --link-mode copy --python "$VENV/bin/python" --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1+cpu"
"$UV" pip install --link-mode copy --python "$VENV/bin/python" --reinstall-package graphrag-sdk "graphrag-sdk[litellm]==1.4.0" "litellm==1.105.1" "gliner==0.2.29" \
  "transformers==5.16.1" "fastembed==0.8.1" "falkordb==1.8.0"

"$VENV/bin/python" - <<'PY'
import pathlib, sys
import graphrag_sdk
assert graphrag_sdk.__version__ == "1.4.0", graphrag_sdk.__version__
p = pathlib.Path(graphrag_sdk.__file__).parent / "storage" / "vector_store.py"
src = p.read_text()
patches = {   # each old literal includes its trailing comma, so the comment cannot swallow it
    "\"CALL db.idx.fulltext.createNodeIndex('Chunk', 'text')\",":
        "\"CREATE FULLTEXT INDEX FOR (n:Chunk) ON (n.text)\",  # faultline eval patch (GraphRAG-SDK #344)",
    "\"CALL db.idx.fulltext.createNodeIndex('__Entity__', 'name', 'description')\",":
        "\"CREATE FULLTEXT INDEX FOR (n:__Entity__) ON (n.name, n.description)\",  # faultline eval patch (#344)",
}
done = 0
for old, new in patches.items():
    if new in src:
        done += 1
        continue
    if src.count(old) != 1:
        sys.exit(f"patch: expected exactly one {old!r} in {p}; the SDK changed, review the patch")
    src = src.replace(old, new)
    done += 1
tmp = p.with_suffix('.py.patched')
tmp.write_text(src)
tmp.replace(p)   # a new file, never an in-place edit: uv may hard-link package files from its cache
print(f"patched {p} ({done}/2 statements use the DDL form)")
PY

HF_HOME="$DIR/hf" "$VENV/bin/python" -c "from huggingface_hub import snapshot_download; print(snapshot_download('urchade/gliner_medium-v2.1'))"
echo "graphrag-sdk venv ready: $VENV"
