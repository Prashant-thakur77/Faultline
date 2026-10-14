"""GitHub access for the demo repos (systems under observation). Two implementations, one protocol:

* `RealGitHub`: GitHub REST via the `gh` CLI (`gh api`), using the operator's gh auth. Used for the live demo.
* `SimGitHub`:  an in-memory simulated GitHub for keyless tests/judge-check, labelled as simulated in every
                 result (`served_by`). It is the simulated world, not agent state.
Only branches named `faultline/fix-*` may be created or merged (refused otherwise).
"""

from __future__ import annotations

import base64
import json
import threading
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

FIX_PREFIX = "faultline/fix-"


class GitHubError(RuntimeError):
    pass


class GitHubTimeout(GitHubError):
    """The API did not answer in time: the verdict for anything depending on it is UNKNOWN."""


def _check_branch(branch: str) -> None:
    if not branch.startswith(FIX_PREFIX):
        raise GitHubError(f"refusing to touch branch {branch!r}: only {FIX_PREFIX}* is allowed")


from ..preflight.facts import CONFIG_SUFFIXES  # noqa: E402  (the only files the fact extractor parses)
MAX_PR_FILES = 200


class GitHub(Protocol):
    label: str

    def get_file(self, repo: str, path: str, ref: str = "main") -> tuple[str, str]: ...
    def branch_exists(self, repo: str, branch: str) -> bool: ...
    def create_branch(self, repo: str, branch: str, from_ref: str = "main") -> None: ...
    def put_file(self, repo: str, branch: str, path: str, content: str, message: str) -> str: ...
    def open_pr(self, repo: str, head: str, title: str, body: str, base: str = "main") -> dict: ...
    def find_pr(self, repo: str, head: str) -> dict | None: ...
    def merge_pr(self, repo: str, number: int) -> str: ...
    def create_issue(self, repo: str, title: str, body: str) -> dict: ...
    def find_issue(self, repo: str, needle: str) -> dict | None: ...
    def pr_files(self, repo: str, number: int) -> dict: ...


@dataclass
class SimGitHub:
    """In-memory simulated GitHub (keyless). files[repo][branch][path] = content."""

    label: str = "simulated GitHub (no token; keyless mode)"
    files: dict = field(default_factory=dict)
    prs: dict = field(default_factory=dict)
    issues: dict = field(default_factory=dict)
    fail_next: str | None = None  # "timeout" to simulate an API timeout (S9 unknown-verification scenario)

    def _maybe_fail(self) -> None:
        if self.fail_next == "timeout":
            self.fail_next = None
            raise GitHubTimeout("GitHub API timed out (simulated)")

    def seed(self, repo: str, path: str, content: str) -> None:
        self.files.setdefault(repo, {}).setdefault("main", {})[path] = content

    def get_file(self, repo, path, ref="main"):
        self._maybe_fail()
        try:
            c = self.files[repo][ref][path]
        except KeyError as e:
            raise GitHubError(f"{repo}@{ref}:{path} not found") from e
        return c, f"sha-{abs(hash(c)) % 10**12:012d}"

    def branch_exists(self, repo, branch):
        return branch in self.files.get(repo, {})

    def create_branch(self, repo, branch, from_ref="main"):
        _check_branch(branch)
        self.files.setdefault(repo, {})[branch] = dict(self.files[repo][from_ref])

    def put_file(self, repo, branch, path, content, message):
        _check_branch(branch)
        self.files[repo][branch][path] = content
        return f"commit-{abs(hash((branch, content, message))) % 10**10:010d}"

    def open_pr(self, repo, head, title, body, base="main"):
        _check_branch(head)
        n = len(self.prs) + 1
        self.prs[n] = {"number": n, "head": head, "base": base, "title": title, "body": body, "state": "open",
                       "url": f"https://github.com/{repo}/pull/{n} (simulated)"}
        return self.prs[n]

    def find_pr(self, repo, head):
        return next((p for p in self.prs.values() if p["head"] == head), None)

    def merge_pr(self, repo, number):
        self._maybe_fail()
        pr = self.prs[number]
        _check_branch(pr["head"])
        self.files[repo][pr["base"]] = dict(self.files[repo][pr["head"]])
        pr["state"] = "merged"
        return f"merge-{number:06d}"

    def create_issue(self, repo, title, body):
        self._maybe_fail()
        n = len(self.issues) + 1
        self.issues[n] = {"number": n, "title": title, "body": body, "url": f"https://github.com/{repo}/issues/{n} (simulated)"}
        return self.issues[n]

    def find_issue(self, repo, needle):
        self._maybe_fail()
        return next((i for i in self.issues.values() if needle in i["body"]), None)

    def pr_files(self, repo, number):
        """The PR's changed files: head branch vs its base, with before/after contents."""
        self._maybe_fail()
        pr = self.prs.get(int(number))
        if pr is None:
            raise GitHubError(f"{repo}#{number} not found")
        base, head = self.files.get(repo, {}).get(pr["base"], {}), self.files.get(repo, {}).get(pr["head"], {})
        paths = sorted(p for p in set(base) | set(head) if base.get(p) != head.get(p))[:MAX_PR_FILES]
        return {"title": pr["title"], "author": pr.get("author", ""), "head_sha": pr["head"],
                "files": [{"path": p, "before": base.get(p), "after": head.get(p)} for p in paths]}


class RealGitHub:
    """GitHub REST through `gh api` (the operator's existing gh auth; no token is read or printed here)."""

    label = "GitHub REST (gh api)"

    def __init__(self, timeout_s: float = 20.0):
        self.timeout = timeout_s

    def _api(self, *args: str, payload: dict | None = None) -> dict | list:
        cmd = ["gh", "api", *args]
        try:
            r = subprocess.run(cmd + (["--input", "-"] if payload is not None else []), capture_output=True, text=True,
                               timeout=self.timeout, input=json.dumps(payload) if payload is not None else None)
        except subprocess.TimeoutExpired as e:
            raise GitHubTimeout(f"gh api {' '.join(args[:2])} timed out after {self.timeout}s") from e
        if r.returncode != 0:
            raise GitHubError(f"gh api {' '.join(args[:2])} failed: {r.stderr.strip()[:300]}")
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def get_file(self, repo, path, ref="main"):
        d = self._api(f"repos/{repo}/contents/{path}?ref={ref}")
        return base64.b64decode(d["content"]).decode(), d["sha"]

    def branch_exists(self, repo, branch):
        try:
            self._api(f"repos/{repo}/branches/{branch}")
            return True
        except GitHubError:
            return False

    def create_branch(self, repo, branch, from_ref="main"):
        _check_branch(branch)
        sha = self._api(f"repos/{repo}/git/ref/heads/{from_ref}")["object"]["sha"]
        self._api(f"repos/{repo}/git/refs", "-X", "POST", payload={"ref": f"refs/heads/{branch}", "sha": sha})

    def put_file(self, repo, branch, path, content, message):
        _check_branch(branch)
        _, sha = self.get_file(repo, path, branch)
        d = self._api(f"repos/{repo}/contents/{path}", "-X", "PUT", payload={
            "message": message, "content": base64.b64encode(content.encode()).decode(), "sha": sha, "branch": branch})
        return d["commit"]["sha"]

    def open_pr(self, repo, head, title, body, base="main"):
        _check_branch(head)
        d = self._api(f"repos/{repo}/pulls", "-X", "POST", payload={"title": title, "head": head, "base": base, "body": body})
        return {"number": d["number"], "url": d["html_url"], "state": d["state"], "head": head}

    def find_pr(self, repo, head):
        owner = repo.split("/")[0]
        d = self._api(f"repos/{repo}/pulls?head={owner}:{head}&state=all")
        if not d:
            return None
        state = "merged" if d[0].get("merged_at") else d[0]["state"]
        return {"number": d[0]["number"], "url": d[0]["html_url"], "state": state, "head": head}

    def merge_pr(self, repo, number):
        d = self._api(f"repos/{repo}/pulls/{number}/merge", "-X", "PUT", payload={"merge_method": "squash"})
        return d.get("sha", "")

    def create_issue(self, repo, title, body):
        d = self._api(f"repos/{repo}/issues", "-X", "POST", payload={"title": title, "body": body})
        return {"number": d["number"], "url": d["html_url"]}

    def find_issue(self, repo, needle):
        for i in self._api(f"repos/{repo}/issues?state=all&per_page=100"):
            if needle in (i.get("body") or ""):
                return {"number": i["number"], "url": i["html_url"]}
        return None

    def pr_files(self, repo, number):
        """The PR's changed files via REST; contents only for config files (what the fact extractor reads)."""
        pr = self._api(f"repos/{repo}/pulls/{int(number)}")
        files: list = []
        for page in (1, 2):  # up to MAX_PR_FILES (100 per page)
            batch = self._api(f"repos/{repo}/pulls/{int(number)}/files?per_page=100&page={page}")
            files += batch if isinstance(batch, list) else []
            if not isinstance(batch, list) or len(batch) < 100:
                break

        def content(path: str, sha: str) -> str | None:
            try:
                return self.get_file(repo, path, sha)[0]
            except GitHubError:  # added (no before) or removed (no after)
                return None

        out = []
        for f in files[:MAX_PR_FILES]:
            path, cfg = f["filename"], f["filename"].endswith(CONFIG_SUFFIXES)
            out.append({"path": path, "before": content(path, pr["base"]["sha"]) if cfg else None,
                        "after": content(path, pr["head"]["sha"]) if cfg else None})
        return {"title": pr.get("title", ""), "author": (pr.get("user") or {}).get("login", ""),
                "head_sha": pr["head"]["sha"], "files": out}


@dataclass
class FileSimGitHub(SimGitHub):
    """The simulated GitHub persisted to a JSON file (FAULTLINE_SIM_GITHUB_DIR; the SIGKILL chaos test only), so the
    simulated outside world outlives a killed API process the way real GitHub would. State is reloaded before and
    saved after every call (one process at a time; the test sequences them)."""

    path: str = ""

    def _load(self) -> None:
        import os

        if os.path.exists(self.path):
            with open(self.path) as f:
                d = json.load(f)
            self.files, self.issues = d["files"], {int(k): v for k, v in d["issues"].items()}
            self.prs = {int(k): v for k, v in d["prs"].items()}

    def _save(self) -> None:
        import os

        tmp = f"{self.path}.tmp"
        with open(tmp, "w") as f:
            json.dump({"files": self.files, "prs": self.prs, "issues": self.issues}, f, sort_keys=True)
        os.replace(tmp, self.path)


def _persisted(name: str):
    def call(self, *a, **k):
        self._load()
        try:
            return getattr(SimGitHub, name)(self, *a, **k)
        finally:
            self._save()
    return call


for _m in ("seed", "get_file", "branch_exists", "create_branch", "put_file", "open_pr", "find_pr", "merge_pr",
           "create_issue", "find_issue", "pr_files"):
    setattr(FileSimGitHub, _m, _persisted(_m))


# One simulated world per graph (each run's clean room has its own). PROCESS MEMORY: the in-memory simulated GitHub
# starts empty again when the API restarts (only FileSimGitHub, the chaos test's hook, survives a restart), so after a
# restart an intent approved by an earlier process cannot be judged against it: the reconciler treats that world as
# unknown (UNKNOWN, escalated), never as "absent" (review round 5, minor 8). Worlds of collected graphs are dropped.
_SIMS: dict[str, SimGitHub] = {}
_SIMS_LOCK = threading.Lock()


def reset_sim(world: str | None = None) -> None:
    """Re-arm: the simulated world of ONE graph starts over (None: all worlds, tests/tools only). In-flight runs
    live in their own eval graphs, so re-arming the tenant graph never disturbs them."""
    with _SIMS_LOCK:
        if world is None:
            _SIMS.clear()
        else:
            _SIMS.pop(world, None)


def prune_sims(existing: set[str]) -> list[str]:
    """Drop the simulated worlds of graphs that no longer exist (the collector deleted them)."""
    with _SIMS_LOCK:
        gone = [k for k in _SIMS if k != "default" and k not in existing]
        for k in gone:
            _SIMS.pop(k, None)
    return gone


def ephemeral(hub: "GitHub") -> bool:
    """A simulated world that lives only in this process's memory (lost on restart)."""
    return isinstance(hub, SimGitHub) and not isinstance(hub, FileSimGitHub)


def world_id() -> str:
    """Which outside world this process acts in, recorded on every intent it approves: `github` (real), `dir:<path>`
    (the simulated GitHub persisted to FAULTLINE_SIM_GITHUB_DIR), or `mem` (in this process's memory). A reconciler
    only settles an intent recorded in a persisted world it shares; an in-memory world dies with its process, so any
    reconciler may escalate that one (never as success)."""
    import os

    if is_real():
        return "github"
    from ..config import settings

    d = os.environ.get("FAULTLINE_SIM_GITHUB_DIR")
    return f"dir:{os.path.abspath(d)}" if d and not settings.faultline_public else "mem"


def is_real() -> bool:
    import os

    return os.environ.get("FAULTLINE_GITHUB", "sim") == "real"


def client(world: str | None = None, mode: str | None = None) -> GitHub:
    """`real` when explicitly configured (FAULTLINE_GITHUB=real); otherwise the simulated GitHub of `world`
    (the graph the run lives in)."""
    import os

    if (mode or os.environ.get("FAULTLINE_GITHUB", "sim")) == "real":
        return RealGitHub()
    key = world or "default"
    with _SIMS_LOCK:
        return _sim_for(key)


def _sim_for(key: str) -> SimGitHub:
    """The simulated world `key` (caller holds _SIMS_LOCK)."""
    import os

    if key not in _SIMS:
        state_dir = os.environ.get("FAULTLINE_SIM_GITHUB_DIR")  # chaos test only: the world survives a kill -9
        if state_dir:
            from ..config import settings

            if settings.faultline_public:  # a chaos hook: never on the public demo
                import logging

                logging.getLogger("faultline.chaos").error("FAULTLINE_SIM_GITHUB_DIR refused in public mode")
                state_dir = None
        _SIMS[key] = FileSimGitHub(path=os.path.join(state_dir, f"{key}.json")) if state_dir else SimGitHub()
    return _SIMS[key]
