"""Unit tests for the autonomous pull-request step (WORKSTREAM B).

Three properties are load-bearing and are pinned here:

1. **The PR body is a real review artifact** — every section a reviewer needs is
   rendered from the recorded `IncidentState`, and nothing is invented when the
   state is sparse.
2. **The feature is off by default** — `FAULTLINE_CREATE_PR` defaults to false and
   the disabled path does not run a single subprocess, so the demo and the evals
   behave exactly as they did before the PR step existed.
3. **The PR step can never cost us a verified repair** — push/`gh` failures of any
   kind are swallowed into evidence; the incident still reaches VERIFIED.

Everything here is offline: no git, no network, no `gh`. Subprocess access in the
publish path funnels through `repair._run`, which these tests monkeypatch.
"""

import subprocess

import pytest

from faultline import repair
from faultline.config import settings
from faultline.models import (
    EvidenceItem,
    GitArtifact,
    IncidentStage,
    IncidentState,
    LineageEdge,
    LineageNode,
    MetricSnapshot,
    ProposedPatch,
    RootCause,
)
# Aliased on import: pytest tries to collect any module-level name starting with
# `Test`, and these pydantic models are not test classes.
from faultline.models import TestFailure as InvariantFailure
from faultline.models import TestReport as InvariantReport

URN_RAW = "urn:li:dataset:(urn:li:dataPlatform:duckdb,raw.raw_orders,PROD)"
URN_STG = "urn:li:dataset:(urn:li:dataPlatform:duckdb,staging.stg_orders,PROD)"
URN_KPI = "urn:li:dataset:(urn:li:dataPlatform:duckdb,marts.exec_revenue_metric,PROD)"

DIFF = """--- a/pipeline/transforms/stg_orders.sql
+++ b/pipeline/transforms/stg_orders.sql
@@ -1,3 +1,5 @@
 SELECT
-    CAST(amount AS DOUBLE) AS amount,
+    CASE WHEN payment_processor = 'cloudpay_v2'
+         THEN CAST(amount AS DOUBLE) / 100.0
+         ELSE CAST(amount AS DOUBLE) END AS amount,
     currency
"""


# --------------------------------------------------------------------- fixtures




@pytest.fixture()
def pr_off(monkeypatch):
    monkeypatch.setattr(settings, "faultline_create_pr", False, raising=False)


@pytest.fixture()
def pr_on(monkeypatch):
    monkeypatch.setattr(settings, "faultline_create_pr", True, raising=False)


def _completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def fake_runner(responses, calls):
    """Build a `repair._run` replacement.

    `responses` maps a substring of the joined command to (returncode, stdout).
    Every invocation is appended to `calls` so tests can assert what ran — and,
    just as importantly, what did not.
    """

    def _run(cmd, timeout=60):
        calls.append(list(cmd))
        joined = " ".join(cmd)
        for needle, (rc, out) in responses.items():
            if needle in joined:
                return _completed(cmd, returncode=rc, stdout=out, stderr="" if rc == 0 else "boom")
        return _completed(cmd, returncode=1, stderr=f"unexpected command: {joined}")

    return _run


def verified_state() -> IncidentState:
    """A realistic post-verification IncidentState, shaped exactly like the ones the
    tool code writes (payload shapes copied from examples/sample-incident)."""
    state = IncidentState(report_text="Exec revenue dashboard shows a 100x jump since Friday.")
    state.stage = IncidentStage.VERIFIED
    state.nodes = [
        LineageNode(urn=URN_RAW, name="raw.raw_orders", platform="duckdb", layer="source"),
        LineageNode(urn=URN_STG, name="staging.stg_orders", platform="duckdb", layer="staging"),
        LineageNode(urn=URN_KPI, name="marts.exec_revenue_metric", platform="duckdb", layer="metric"),
    ]
    state.edges = [LineageEdge(source=URN_RAW, target=URN_STG), LineageEdge(source=URN_STG, target=URN_KPI)]

    lineage_ev = EvidenceItem(
        kind="lineage", source="falkordb", title="Lineage upstream of marts.exec_revenue_metric",
        detail="6 nodes / 5 edges from the graph",
        data={"root": URN_KPI, "direction": "UPSTREAM", "nodes": [{"urn": URN_RAW}]},
    )
    metadata_ev = EvidenceItem(
        kind="metadata", source="falkordb", title="Graph context: raw.raw_orders",
        detail="schema + contract + ownership retrieved",
        data={"urn": URN_RAW, "description": "amount is a decimal in major currency units"},
    )
    baseline_ev = EvidenceItem(
        kind="baseline_comparison", source="warehouse", title="Baseline comparison (last 10 days)",
        detail="days over 1.5x baseline: ['2026-08-09']",
        data={
            "comparisons": [
                {
                    "day": "2026-08-09", "revenue_usd": 2737323.5, "baseline_revenue_usd": 27373.23,
                    "revenue_ratio": 100.0, "aov_median_usd": 6213.0,
                    "baseline_aov_median_usd": 62.13, "order_count": 327, "baseline_order_count": 327,
                },
                {
                    "day": "2026-08-06", "revenue_usd": 33372.65, "baseline_revenue_usd": 33372.65,
                    "revenue_ratio": 1.0, "aov_median_usd": 64.44,
                    "baseline_aov_median_usd": 64.44, "order_count": 406, "baseline_order_count": 406,
                },
            ]
        },
    )
    profile_ev = EvidenceItem(
        kind="profile", source="warehouse", title="Profile raw.raw_orders.amount by payment_processor",
        detail="7 day×segment rows",
        data={
            "table": "raw.raw_orders", "column": "amount", "segment_by": "payment_processor",
            "days": [
                {"day": "2026-08-09", "segment": "cloudpay_v2", "n": 342, "mean": 8238.5702,
                 "median": 6076.0, "min": 1223.0, "max": 55262.0, "null_rate": 0.0},
                {"day": "2026-08-06", "segment": "legacy_pos", "n": 295, "mean": 86.2854,
                 "median": 61.66, "min": 10.2, "max": 877.94, "null_rate": 0.0},
            ],
        },
    )
    # An uncited item: it must count in the by-source census but must not be quoted
    # as if the root cause rested on it.
    uncited_ev = EvidenceItem(
        kind="sql", source="warehouse", title="Ad-hoc SQL", detail="SELECT 1", data={"rows": []}
    )
    state.evidence = [lineage_ev, metadata_ev, baseline_ev, profile_ev, uncited_ev]

    state.root_cause = RootCause(
        summary=(
            "On 2026-08-07 the payments platform cut the order feed over to the cloudpay_v2 "
            "processor, which reports raw_orders.amount in minor units (cents) instead of the "
            "contractually required major units — silently multiplying revenue by exactly 100x."
        ),
        asset_urn=URN_RAW,
        field="amount",
        detail="order_count is identical to baseline while AOV is inflated 100x.",
        evidence_ids=[lineage_ev.id, metadata_ev.id, baseline_ev.id, profile_ev.id],
    )
    state.patch = ProposedPatch(
        file="pipeline/transforms/stg_orders.sql", diff=DIFF,
        reasoning="Normalise cloudpay_v2 minor units to major units at the staging boundary.",
        status="verified",
    )
    state.tests_before = InvariantReport(
        total=32, passed=25, failed=7,
        failures=[InvariantFailure(name="test_max_usd_amount_sane", message="max usd order amount 55262.00 >= 10000")],
    )
    state.tests_after = InvariantReport(total=32, passed=32, failed=0)
    state.metric_before = MetricSnapshot(
        kpi_day="2026-08-09", revenue=2737323.5, expected_revenue=29349.39,
        anomaly_ratio=93.2668, status="anomalous",
    )
    state.metric_after = MetricSnapshot(
        kpi_day="2026-08-09", revenue=27373.23, expected_revenue=29349.39,
        anomaly_ratio=0.9327, status="ok",
    )
    state.git_artifact = GitArtifact(
        branch=f"faultline/fix-{state.id}", commit="03ccf05564aa855299be84a88ba85d70eaab929a",
        diff_stat="1 file changed, 18 insertions(+), 1 deletion(-)",
    )
    return state


# ------------------------------------------------------------------- PR title


def test_pr_title_is_conventional_and_short():
    state = verified_state()
    title = repair.build_pr_title(state)
    assert title.startswith("fix(pipeline): ")
    assert len(title) <= 72
    assert "\n" not in title
    # truncation happens on a word boundary, not mid-word
    assert title.endswith("...")
    assert " ..." not in title


def test_pr_title_survives_a_stateless_incident():
    state = IncidentState(report_text="something is off")
    title = repair.build_pr_title(state)
    assert title.startswith("fix(pipeline): ")
    assert state.id in title
    assert len(title) <= 72


# -------------------------------------------------------------------- PR body


def test_pr_body_has_every_required_section():
    body = repair.build_pr_body(verified_state())

    # 1. disclosure header: autonomous authorship AND synthetic-fixture disclosure
    header = body[: body.index("## Root cause")]
    assert "Faultline" in header
    assert "autonomous agent" in header.lower()
    assert "verified" in header.lower()
    assert "synthetic" in header.lower() and "fixture" in header.lower()
    assert "deterministic" in header.lower()

    for section in (
        "## Root cause",
        "## Graph evidence",
        "## Quantitative proof",
        "## Verification — KPI before / after",
        "## Verification — pipeline invariants",
    ):
        assert section in body, f"missing section: {section}"


def test_pr_body_blames_a_concrete_asset_and_field():
    state = verified_state()
    body = repair.build_pr_body(state)
    assert state.root_cause.summary in body
    assert URN_RAW in body
    assert "`amount`" in body


def test_pr_body_summarises_graph_evidence_by_source():
    state = verified_state()
    body = repair.build_pr_body(state)
    section = body[body.index("## Graph evidence"): body.index("## Quantitative proof")]
    # census over ALL evidence, counted per source
    assert "5 evidence item(s)" in section
    assert "`falkordb` × 2" in section
    assert "`warehouse` × 3" in section
    # the cited lineage + metadata facts are named with their ids
    assert "Lineage upstream of marts.exec_revenue_metric" in section
    assert "Graph context: raw.raw_orders" in section
    for ev in state.evidence[:2]:
        assert ev.id in section


def test_pr_body_quantitative_proof_comes_from_evidence_payloads():
    state = verified_state()
    body = repair.build_pr_body(state)
    section = body[body.index("## Quantitative proof"): body.index("## The fix")]
    # baseline comparison numbers, rendered from the cited evidence item's data
    assert "2026-08-09" in section
    assert "2,737,323.50" in section
    assert "27,373.23" in section
    assert "100.000x" in section
    assert "327 / 327" in section
    # profile numbers for the blamed column
    assert "cloudpay_v2" in section
    assert "6,076" in section
    assert "raw.raw_orders" in section and "amount" in section
    # the uncited SQL item is not dressed up as root-cause proof
    assert "Ad-hoc SQL" not in section


def test_pr_body_embeds_the_real_diff_in_a_diff_block():
    state = verified_state()
    body = repair.build_pr_body(state)
    assert "```diff" in body
    block = body.split("```diff", 1)[1].split("```", 1)[0]
    assert "CASE WHEN payment_processor = 'cloudpay_v2'" in block
    assert "/ 100.0" in block
    assert state.patch.file in body
    assert state.patch.reasoning in body


def test_pr_body_reports_before_after_kpi_and_invariants():
    state = verified_state()
    body = repair.build_pr_body(state)
    kpi = body[body.index("## Verification — KPI before / after"):]
    assert "93.2668x" in kpi
    assert "0.9327x" in kpi
    assert "2,737,323.50" in kpi and "27,373.23" in kpi
    assert "anomalous" in kpi and "ok" in kpi
    assert "32/32 passed" in body
    assert "25/32" in body  # before-state, for contrast
    assert "test_max_usd_amount_sane" in body


def test_pr_body_states_the_incident_id_and_git_provenance():
    state = verified_state()
    body = repair.build_pr_body(state)
    assert state.id in body
    assert state.git_artifact.branch in body
    assert state.git_artifact.commit[:10] in body


def test_pr_body_invents_nothing_for_a_sparse_incident():
    """A half-recorded incident must degrade to honest 'not recorded' text rather
    than plausible-looking numbers."""
    state = IncidentState(report_text="revenue looks wrong")
    body = repair.build_pr_body(state)
    assert "No confirmed root cause" in body
    assert "No quantitative evidence" in body
    assert "No patch was recorded" in body
    assert "No post-repair invariant run" in body
    assert "n/a" in body
    assert "```diff" not in body


# ------------------------------------------------------------ the feature flag


def test_pr_creation_is_off_by_default(monkeypatch):
    """The shipped default must never push to a remote.

    Checked against a Settings built with no `.env` and no env var, so a developer
    who opts in locally does not turn this guarantee green by accident.
    """
    from faultline.config import Settings

    monkeypatch.delenv("FAULTLINE_CREATE_PR", raising=False)
    assert Settings(_env_file=None).faultline_create_pr is False
    assert Settings.model_fields["faultline_create_pr"].default is False


def test_disabled_flag_runs_no_subprocess_at_all(pr_off, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(repair, "_run", fake_runner({}, calls))
    state = verified_state()
    artifact = state.git_artifact

    out = repair.publish_repair_pr(state, artifact)

    assert out["status"] == "disabled"
    assert out["url"] is None
    assert artifact.pr_url is None
    assert calls == [], "the disabled path must not shell out"


# --------------------------------------------------------------- push safety


def test_only_fix_branches_may_be_pushed(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(repair, "_run", fake_runner({}, calls))
    for branch in ("main", "master", "feature/whatever"):
        out = repair.try_create_pr(GitArtifact(branch=branch, commit="abc", diff_stat=""), "t", "b")
        assert out["status"] == "failed"
        assert "refusing to push" in out["detail"]
    assert calls == [], "a non-fix branch must be rejected before any git invocation"


def test_push_targets_only_the_fix_branch_ref(pr_on, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        repair, "_run",
        fake_runner(
            {
                "git remote": (0, "origin\n"),
                "gh auth status": (0, "Logged in"),
                "git push": (0, ""),
                "gh pr create": (0, "https://github.com/acme/faultline/pull/7\n"),
            },
            calls,
        ),
    )
    state = verified_state()
    artifact = state.git_artifact

    out = repair.publish_repair_pr(state, artifact)

    assert out["status"] == "created"
    assert out["url"] == "https://github.com/acme/faultline/pull/7"
    assert artifact.pr_url == "https://github.com/acme/faultline/pull/7"

    pushes = [c for c in calls if c[:2] == ["git", "push"]]
    assert len(pushes) == 1, "a successful push must not be retried"
    refspec = pushes[0][-1]
    assert refspec == f"refs/heads/{artifact.branch}:refs/heads/{artifact.branch}"
    assert "main" not in refspec and "master" not in refspec
    assert "--force" not in pushes[0]
    assert pushes[0][2] == "origin", "only `origin` may be pushed to"

    created = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert created and "--body-file" in created[0]
    assert created[0][created[0].index("--title") + 1].startswith("fix(pipeline): ")


def test_no_push_without_origin_or_gh_auth(pr_on, monkeypatch):
    # (a) no origin remote -> skipped before any push
    calls: list[list[str]] = []
    monkeypatch.setattr(repair, "_run", fake_runner({"git remote": (0, "upstream\n")}, calls))
    out = repair.publish_repair_pr(verified_state(), GitArtifact(branch="faultline/fix-x", commit="a", diff_stat=""))
    assert out["status"] == "skipped" and "origin" in out["detail"]
    assert not [c for c in calls if c[:2] == ["git", "push"]]

    # (b) origin exists but gh is unauthenticated -> still no push
    calls = []
    monkeypatch.setattr(
        repair, "_run",
        fake_runner({"git remote": (0, "origin\n"), "gh auth status": (1, "")}, calls),
    )
    out = repair.publish_repair_pr(verified_state(), GitArtifact(branch="faultline/fix-x", commit="a", diff_stat=""))
    assert out["status"] == "skipped" and "gh auth status" in out["detail"]
    assert not [c for c in calls if c[:2] == ["git", "push"]]


def test_missing_gh_binary_is_treated_as_not_ready(pr_on, monkeypatch):
    def _run(cmd, timeout=60):
        if cmd[0] == "gh":
            raise FileNotFoundError("gh")
        return _completed(cmd, stdout="origin\n")

    monkeypatch.setattr(repair, "_run", _run)
    out = repair.publish_repair_pr(verified_state(), GitArtifact(branch="faultline/fix-x", commit="a", diff_stat=""))
    assert out["status"] == "skipped"


# --------------------------------------------------- failure isolation (unit)


@pytest.mark.parametrize(
    "responses, expected",
    [
        # push rejected by the remote (and the single permitted retry also fails)
        ({"git remote": (0, "origin\n"), "gh auth status": (0, ""), "git push": (1, "")}, "failed"),
        # push works, gh rate-limits / errors and no PR exists to fall back to
        (
            {"git remote": (0, "origin\n"), "gh auth status": (0, ""), "git push": (0, ""),
             "gh pr create": (1, ""), "gh pr view": (1, "")},
            "failed",
        ),
    ],
)
def test_remote_failures_are_reported_not_raised(pr_on, monkeypatch, responses, expected):
    calls: list[list[str]] = []
    monkeypatch.setattr(repair, "_run", fake_runner(responses, calls))
    artifact = GitArtifact(branch="faultline/fix-x", commit="a", diff_stat="")

    out = repair.publish_repair_pr(verified_state(), artifact)

    assert out["status"] == expected
    assert out["url"] is None
    assert artifact.pr_url is None, "a failed publication must not fake a PR url"
    assert out["detail"]


def test_existing_pr_is_reused_instead_of_failing(pr_on, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        repair, "_run",
        fake_runner(
            {"git remote": (0, "origin\n"), "gh auth status": (0, ""), "git push": (0, ""),
             "gh pr create": (1, ""), "gh pr view": (0, "https://github.com/acme/faultline/pull/3\n")},
            calls,
        ),
    )
    artifact = GitArtifact(branch="faultline/fix-x", commit="a", diff_stat="")
    out = repair.publish_repair_pr(verified_state(), artifact)
    assert out["status"] == "created"
    assert artifact.pr_url == "https://github.com/acme/faultline/pull/3"


def test_any_exception_in_the_publish_path_is_swallowed(pr_on, monkeypatch):
    def _explode(cmd, timeout=60):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(repair, "_run", _explode)
    artifact = GitArtifact(branch="faultline/fix-x", commit="a", diff_stat="")

    out = repair.publish_repair_pr(verified_state(), artifact)  # must not raise

    assert out["status"] == "failed"
    assert artifact.pr_url is None
    assert "TimeoutExpired" in out["detail"]


def test_a_broken_pr_body_does_not_break_publication_reporting(pr_on, monkeypatch):
    monkeypatch.setattr(
        repair, "build_pr_body", lambda state: (_ for _ in ()).throw(ValueError("bad state"))
    )
    monkeypatch.setattr(repair, "_run", lambda cmd, timeout=60: pytest.fail("must not shell out"))
    artifact = GitArtifact(branch="faultline/fix-x", commit="a", diff_stat="")

    out = repair.publish_repair_pr(verified_state(), artifact)

    assert out["status"] == "failed"
    assert "ValueError" in out["detail"]
    assert artifact.pr_url is None


# --------------------------------------- failure isolation (through the tool)


def _stub_verified_repair(monkeypatch, state):
    """Make t_propose_repair reach VERIFIED without touching the warehouse."""
    patch = ProposedPatch(file="pipeline/transforms/stg_orders.sql", diff=DIFF, reasoning="r")
    monkeypatch.setattr(repair, "propose_patch", lambda f, c, r: patch)
    monkeypatch.setattr(repair, "apply_patch", lambda p, c: None)
    monkeypatch.setattr(
        repair, "verify_repair",
        lambda: (
            InvariantReport(total=32, passed=32, failed=0),
            MetricSnapshot(kpi_day="2026-08-09", revenue=27373.23, expected_revenue=29349.39,
                           anomaly_ratio=0.9327, status="ok"),
            True,
        ),
    )
    monkeypatch.setattr(
        repair, "make_git_artifact",
        lambda p, iid, s: GitArtifact(branch=f"faultline/fix-{iid}", commit="deadbeefcafe", diff_stat="1 file"),
    )
    return patch
