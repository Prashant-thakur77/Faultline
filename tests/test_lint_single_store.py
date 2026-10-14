import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lint_single_store", ROOT / "scripts" / "lint_single_store.py")
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def _pkg(tmp_path, files):
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
    return tmp_path


def test_repo_passes():
    assert lint.main([]) == 0


def test_catches_other_store_imports(tmp_path):
    root = _pkg(tmp_path, {"agent/x.py": "import networkx\n", "memory/y.py": "import sqlite3\n"})
    assert lint.main([str(root)]) == 1


def test_catches_runtime_json_state_and_python_traversal(tmp_path):
    root = _pkg(tmp_path, {
        "agent/a.py": "import json\nstate = json.load(open('s.json'))\n",
        "brain/b.py": "def shortest_path(g, a, b):\n    return []\n",
    })
    assert lint.main([str(root)]) == 1


def test_catches_cypher_fstring_outside_graph(tmp_path):
    root = _pkg(tmp_path, {"agent/c.py": "x = 1\nq = f\"MATCH (n {{id:'{x}'}}) RETURN n\"\n"})
    assert lint.main([str(root)]) == 1


def test_clean_package_passes(tmp_path):
    root = _pkg(tmp_path, {"agent/ok.py": "from ..graph.ro import RO\n\ndef f(ro):\n    return ro.run('Q-META-1', {})\n"})
    assert lint.main([str(root)]) == 0


def test_review_gaps_are_caught(tmp_path):
    cases = {
        "agent/a.py": "import numpy as np\n",
        "memory/b.py": "from json import load\n",
        "brain/c.py": "from collections import deque as dq\n",
        "agent/d.py": "def walk(g, s):\n    q = [s]\n    while q:\n        x = q.pop(0)\n    return x\n",
        "agent/e.py": "q = 'MATCH (n {id:%s}) RETURN n' % 'x'\n",
        "agent/f.py": "q = 'MATCH (n {{id:{}}}) RETURN n'.format('x')\n",
        "agent/g.py": "q = 'MATCH (n)-[:R]->(m) ' + 'RETURN m'\n",
        "memory/h.py": "import pickle\n",
    }
    for rel, src in cases.items():
        root = _pkg(tmp_path / rel.replace('/', '_'), {rel: src})
        assert lint.main([str(root)]) == 1, rel


def test_decoding_a_graph_property_is_allowed(tmp_path):
    root = _pkg(tmp_path, {"agent/ok2.py": "import json\n\ndef f(row):\n    return json.loads(row['checks'])\n",
                           "agent/bad2.py": "import json\nfrom pathlib import Path\nx = json.loads(Path('s.json').read_text())\n"})
    assert lint.main([str(root)]) == 1
    root2 = _pkg(tmp_path / "only_ok", {"agent/ok2.py": "import json\n\ndef f(row):\n    return json.loads(row['checks'])\n"})
    assert lint.main([str(root2)]) == 0
