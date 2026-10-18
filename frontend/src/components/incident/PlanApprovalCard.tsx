"use client";

import { useId, useRef, useState } from "react";
import Link from "next/link";
import {
  Ban,
  Check,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleX,
  Copy,
  ExternalLink,
  FileDiff,
  GitBranch,
  GitPullRequest,
  History,
  Info,
  LoaderCircle,
  Telescope,
  OctagonAlert,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Stamp,
  ThumbsDown,
  Ticket,
  type LucideIcon,
} from "lucide-react";
import {
  api,
  ApiError,
  errorText,
  FOREIGN_RUN_TEXT,
  isForeignRun,
} from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { fmtValue } from "@/lib/format";
import { useAppStatus } from "@/components/AppShell";
import { guidelineFrom409 } from "@/lib/learned";
import { useNow } from "@/hooks/usePolled";
import type {
  OptionFuture,
  ActionOption,
  ApproveResponse,
  ExactAction,
  FixHistoryRow,
  LearnedHook,
  OptionGuideline,
  PlanResponse,
  RejectResponse,
  RemedySummary,
  StageRow,
  TelemetryChannel,
  Verdict,
  WhoFixesRow,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { QUERY_ID_CLS } from "@/components/cypher/ViaFalkor";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusChip } from "@/components/StatusChip";
import { cn } from "@/lib/utils";
import { PlanPending } from "./ContainmentCard";
import { DiffView } from "./DiffView";
import { FixHistoryChip } from "./MemoryCard";
import { Section } from "./Section";
import { ContractGrant } from "@/components/oncall/ContractGrant";
import {
  GuidelineBanner,
  LearnedPlanNote,
  MovedLine,
  movedFrom,
  optionLearned,
  OverrideFields,
  PreferenceLine,
  stripLearnedLines,
  SuggestionChip,
} from "./LearnedBits";

const KIND_TEXT: Record<string, string> = {
  flip_flag: "feature flag",
  rollback_deploy: "rollback",
  open_issue: "issue",
  data_repair: "data repair",
};

const POST_STEPS = ["EXECUTE", "VERIFY", "WRITEBACK"] as const;

const VERDICT_META: Record<
  Verdict,
  {
    cls: string;
    icon: LucideIcon;
    glyph: string;
    text: string;
    meaning: string;
  }
> = {
  APPLIED: {
    cls: "border-emerald-400 bg-emerald-500/15 text-emerald-100",
    icon: CircleCheck,
    glyph: "✓",
    text: "APPLIED",
    meaning: "both verification channels confirm the change took effect",
  },
  NOT_APPLIED: {
    cls: "border-amber-400 bg-amber-500/15 text-amber-100",
    icon: CircleX,
    glyph: "✗",
    text: "NOT_APPLIED",
    meaning:
      "a verification channel shows the change did not take effect; no success write-back",
  },
  UNKNOWN: {
    cls: "border-red-400 bg-red-500/15 text-red-100",
    icon: CircleHelp,
    glyph: "?",
    text: "UNKNOWN",
    meaning:
      "verification could not decide; handed to a human, no success write-back",
  },
};

interface Props {
  incidentId: string;
  stage: string;
  stages: StageRow[];
  plan: PlanResponse | null;
  error: string | null;
  /** Re-read /plan (after choose / approve). */
  onRefresh: () => void;
  /** Called once /approve returns 200: follow EXECUTE → VERIFY → WRITEBACK → RESOLVED. */
  onApproved: () => void;
  /** Replay: show the recorded plan, never POST /choose or /approve. */
  readOnly?: boolean;
  /** report.remedy: what the learned ordering did (absent on older backends / recordings). */
  remedy?: RemedySummary | null;
  /** Opens the remedy_stats query (Q-REM-1) behind the ordering, when it was recorded. */
  onOpenRemedy?: (() => void) | null;
  /** M21: the recorded learned_preferences read behind the learned order (template + opener), when it was recorded. */
  learnedQuery?: { template: string | null; onOpen: () => void } | null;
}

/**
 * Plan & approval (the hero beat). Two steps, bound by a plan hash: choosing an option is not
 * approving it. Step 1 POSTs /choose and shows the exact action the server will take (repo,
 * branch, diff, commit with its Faultline-Idem trailer, rollback, plan hash). Step 2 POSTs
 * /approve with that plan hash; a stale hash is refused with 409 and shown inline.
 */
export function PlanApprovalCard({
  incidentId,
  stage,
  stages,
  plan,
  error,
  onRefresh,
  onApproved,
  readOnly = false,
  remedy = null,
  onOpenRemedy = null,
  learnedQuery = null,
}: Props) {
  const tenant = useTenant();
  // the server says whether approvals act on real GitHub or a simulated one (absent on older backends: no note)
  const github = useAppStatus().status?.github;
  const options = plan?.options ?? [];
  const done =
    options.find((o) => o.status === "approved" || o.status === "executed") ??
    null;
  const chosenOpt = options.find((o) => o.status === "chosen") ?? null;
  const history = plan?.memory?.fix_history ?? [];

  const [chosen, setChosen] = useState<{
    id: string;
    action: ExactAction;
  } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [chooseErr, setChooseErr] = useState<{
    id: string;
    text: string;
  } | null>(null);
  const [approvedBy, setApprovedBy] = useState<
    ApproveResponse["approver"] | null
  >(null);
  // M21: the override this session's approval carried, and whether the approval was learned
  const [approvalExtra, setApprovalExtra] = useState<Pick<
    ApproveResponse,
    "override" | "learned"
  > | null>(null);
  const [rejection, setRejection] = useState<{
    option: string;
    res: RejectResponse;
  } | null>(null);
  // Ranked who-fixes people (Q-WHO-*): the approver field is pre-filled with the top one.
  const candidates = plan?.who_fixes?.payload?.rows ?? [];

  const failed = options.filter((o) => o.status === "failed");
  // A choice made in this session stays valid only while its option is still offered (a NOT_APPLIED
  // verdict disables it and sends the incident back here); after a reload the chosen option's spec is
  // the exact action the server rendered.
  const live =
    chosen &&
    options.some(
      (o) =>
        o.id === chosen.id &&
        o.enabled &&
        (o.status === "option" || o.status === "chosen"),
    );
  const exact = live
    ? chosen
    : chosenOpt?.spec
      ? { id: chosenOpt.id, action: chosenOpt.spec }
      : null;
  const lastPause =
    [...stages]
      .filter((x) => x.stage === "AWAITING_APPROVAL")
      .sort((a, b) => a.at - b.at)
      .at(-1) ?? null;

  const choose = async (id: string) => {
    setBusyId(id);
    setChooseErr(null);
    try {
      const action = await api.choose(incidentId, id, tenant);
      setChosen({ id, action });
      onRefresh();
    } catch (e) {
      setChooseErr({
        id,
        text: isForeignRun(e)
          ? FOREIGN_RUN_TEXT
          : e instanceof ApiError && e.status === 409
            ? `409: ${e.detail}`
            : errorText(e),
      });
    } finally {
      setBusyId(null);
    }
  };

  let body: React.ReactNode;
  if (done) {
    body = (
      <div className="space-y-3">
        <ActionOutcome
          option={done}
          stages={stages}
          plan={plan!}
          approvedBy={approvedBy}
          extra={approvalExtra}
          paged={!readOnly}
        />
        {/* M19: a verified fix can become a standing approval for its repeats (live room only); M21: Faultline
            suggests one when the same exact fix was approved and verified on enough incidents of this family */}
        {!readOnly && done.verdict === "APPLIED" ? (
          <ContractGrant
            incidentId={incidentId}
            actionId={done.id}
            actionKind={done.kind}
            candidates={candidates}
            suggestion={optionLearned(done)?.contract_suggestion ?? null}
            family={optionLearned(done)?.family ?? null}
          />
        ) : null}
      </div>
    );
  } else if (!plan) {
    body = <PlanPending error={error} stage={stage} what="plan" />;
  } else if (stage !== "AWAITING_APPROVAL" || readOnly) {
    body =
      options.length === 0 ? (
        <PlanPending error={error} stage={stage} what="action options" />
      ) : (
        <>
          <p className="mb-2 text-sm text-zinc-300">
            {readOnly ? (
              "Recorded options (read-only: approval happens only in the live incident room)."
            ) : (
              <>
                Approval opens once the run pauses for a human decision (current
                stage: <span className="font-mono">{stage}</span>).
              </>
            )}
          </p>
          {failed.length ? (
            <FailedAttempts failed={failed} note={lastPause?.note ?? null} />
          ) : null}
          <RemedyNote remedy={remedy} onOpen={onOpenRemedy} />
          <LearnedPlanNote learned={plan.learned} query={learnedQuery} />
          <OptionList
            options={options}
            history={history}
            exactId={null}
            busyId={null}
            chooseErr={null}
            onChoose={null}
            tenant={tenant}
          />
        </>
      );
  } else {
    body = (
      <div className="space-y-3">
        {failed.length ? (
          <FailedAttempts failed={failed} note={lastPause?.note ?? null} />
        ) : null}
        {rejection ? (
          <p
            role="status"
            className="flex items-start gap-1.5 rounded-md border border-amber-400/60 bg-amber-500/10 p-2 text-xs text-amber-50"
          >
            <ThumbsDown
              aria-hidden
              className="mt-0.5 size-3.5 shrink-0 text-amber-300"
            />
            <span>
              <strong className="font-semibold">Rejected:</strong>{" "}
              {rejection.option}, by{" "}
              <span className="font-mono">{rejection.res.approver.id}</span>{" "}
              (&ldquo;{rejection.res.reason}&rdquo;). The option is now disabled
              and recorded in the graph; the incident still awaits approval, so
              choose another option.
              <RejectionLearned learned={rejection.res.learned} tenant={tenant} />
            </span>
          </p>
        ) : null}
        <StepHeading n={1} title="Choose an option" done={!!exact} />
        <RemedyNote remedy={remedy} onOpen={onOpenRemedy} />
        <LearnedPlanNote learned={plan.learned} query={learnedQuery} />
        <OptionList
          options={options}
          history={history}
          exactId={exact?.id ?? null}
          busyId={busyId}
          chooseErr={chooseErr}
          onChoose={(id) => void choose(id)}
          tenant={tenant}
        />
        {exact ? (
          <>
            <ExactActionView action={exact.action} />
            <StepHeading n={2} title="Approve this exact action" done={false} />
            <ApproveForm
              key={exact.action.plan_hash}
              incidentId={incidentId}
              actionId={exact.id}
              planHash={exact.action.plan_hash}
              candidates={candidates}
              guideline={activeGuideline(options.find((o) => o.id === exact.id) ?? null)}
              onRechoose={() => void choose(exact.id)}
              onRejected={(res) => {
                setRejection({
                  option:
                    options.find((o) => o.id === exact.id)?.option ?? exact.id,
                  res,
                });
                setChosen(null);
                onRefresh();
              }}
              onApproved={(res) => {
                setApprovedBy(res.approver ?? null);
                setApprovalExtra({ override: res.override ?? null, learned: res.learned ?? null });
                onApproved();
                onRefresh();
              }}
            />
          </>
        ) : (
          <p className="text-xs text-zinc-400">
            Step 2 (approve) unlocks once the server has rendered the exact
            action.
          </p>
        )}
      </div>
    );
  }

  return (
    <Section
      id="plan"
      title="Plan & approval"
      aside={
        done?.verdict ? (
          <VerdictChip verdict={done.verdict} />
        ) : stage === "AWAITING_APPROVAL" ? (
          <StatusChip tone="warn" icon={Stamp}>
            awaiting approval
          </StatusChip>
        ) : null
      }
    >
      {!readOnly && github === "simulated" ? <SimulatedGitHubNote /> : null}
      {body}
    </Section>
  );
}

/** Where the simulated pull requests of the public demo (no GitHub token on the server) are shown for real. */
const DEMO_INFRA_PRS = "https://github.com/Prashant-thakur77/faultline-demo-infra/pulls?q=is%3Apr";

/** One calm line on a server whose approvals act on a simulated GitHub (GET /api/status github: "simulated"). */
function SimulatedGitHubNote() {
  return (
    <p className="mb-3 flex items-start gap-1.5 text-xs leading-relaxed text-zinc-400">
      <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--fl-subtle)]" />
      <span>
        GitHub here is simulated: the fix is a simulated pull request; the real-GitHub path is shown in the video and
        the{" "}
        <a
          href={DEMO_INFRA_PRS}
          target="_blank"
          rel="noreferrer"
          className="rounded text-sky-300 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          faultline-demo-infra repo
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        .
      </span>
    </p>
  );
}

function StepHeading({
  n,
  title,
  done,
}: {
  n: number;
  title: string;
  done: boolean;
}) {
  return (
    <h3 className="flex items-center gap-2 text-[13px] font-medium text-zinc-100">
      <span
        className={cn(
          "inline-flex size-5 items-center justify-center rounded-full border text-[11px]",
          done
            ? "border-emerald-400 bg-emerald-500/20 text-emerald-200"
            : "border-sky-400 text-sky-200",
        )}
      >
        {done ? <Check aria-hidden className="size-3" /> : n}
      </span>
      Step {n} of 2: {title}
      {done ? (
        <span className="font-normal text-emerald-300">(done)</span>
      ) : null}
    </h3>
  );
}

/** The ACTIVE guideline the option is against, as the plan recorded it (an override is needed to approve it). */
function activeGuideline(o: ActionOption | null): OptionGuideline | null {
  const g = o ? optionLearned(o)?.guideline : null;
  return g && g.needs_override ? g : null;
}

/** What the rejection taught Faultline: a proposed guideline from the reason, or why it was not learned. */
function RejectionLearned({
  learned,
  tenant,
}: {
  learned: LearnedHook | null | undefined;
  tenant: string;
}) {
  if (!learned) return null;
  if (!learned.learned) {
    return (
      <span className="mt-1 block text-amber-100/80">
        Not learned: {learned.why}.
      </span>
    );
  }
  return (
    <span className="mt-1 block text-amber-100/90">
      {learned.guideline ? (
        <>
          Faultline proposed guideline{" "}
          <span className="font-mono">{learned.guideline.id}</span> from your
          reason: it shows on the next plan for {learned.family}. Promote or
          dismiss it under{" "}
          <Link
            href={`/memory?tenant=${encodeURIComponent(tenant)}#learned`}
            className="rounded text-sky-200 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            What Faultline has learned
          </Link>
          .
        </>
      ) : (
        <>Learned as a rejection for {learned.family}.</>
      )}
    </span>
  );
}

const HISTORY_SEP = "; history: ";
const FUTURE_SEP = "; future: ";

const FUTURE_TEXT: Record<
  OptionFuture["predicted"],
  { tone: "pass" | "warn" | "na"; text: string }
> = {
  contains: { tone: "pass", text: "predicted: contains" },
  does_not_contain: { tone: "warn", text: "predicted: does not contain" },
  unknown: { tone: "na", text: "predicted: unknown" },
};

/** The option's predicted future (futures, Q-FUTURE-1): the object, or the JSON text /plan reads from the graph. */
function optionFuture(o: Pick<ActionOption, "future">): OptionFuture | null {
  const f = o.future;
  if (!f) return null;
  if (typeof f !== "string") return f;
  try {
    const v = JSON.parse(f) as OptionFuture;
    return v && typeof v.predicted === "string" ? v : null;
  } catch {
    return null;
  }
}

/**
 * An option's reason, split into the static reason and the learned-ordering line
 * ("history: rollback worked 6/6 times on …") that act.order_by_history appends.
 */
function splitReason(o: Pick<ActionOption, "reason" | "history">): {
  base: string | null;
  learned: string | null;
} {
  let r = o.reason ?? "";
  const f = r.indexOf(FUTURE_SEP); // the future is shown as its own line (build_options appends it before history)
  if (f >= 0) {
    const h = r.indexOf(HISTORY_SEP, f);
    r = r.slice(0, f) + (h >= 0 ? r.slice(h) : "");
  }
  const i = r.indexOf(HISTORY_SEP);
  if (i >= 0) return { base: r.slice(0, i) || null, learned: r.slice(i + 2) };
  return { base: r || null, learned: o.history?.line ?? null };
}

/** "6/6" from a history line or the option's history object (display only; the server computed it). */
function workedRatio(o: ActionOption, learned: string): string | null {
  if (o.history) return `${o.history.successes}/${o.history.n}`;
  return learned.match(/worked (\d+\/\d+) times/)?.[1] ?? null;
}

/** What the learned remediation ordering did for this plan (report.remedy, Q-REM-1). */
function RemedyNote({
  remedy,
  onOpen,
}: {
  remedy: RemedySummary | null;
  onOpen: (() => void) | null;
}) {
  if (!remedy || !remedy.note) return null;
  return (
    <p className="mb-3 flex flex-wrap items-start gap-1.5 text-xs text-zinc-400">
      <History
        aria-hidden
        className="mt-0.5 size-3.5 shrink-0 text-[var(--fl-subtle)]"
      />
      <span className="min-w-0 flex-1">
        <span className="font-semibold text-zinc-100">Order:</span>{" "}
        {remedy.note.replace(/[.\s]*$/, ".")}
        {remedy.applied
          ? " It only reorders: no option is added, removed or enabled."
          : ""}
      </span>
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          className={QUERY_ID_CLS}
          aria-label="Q-REM-1: open the Cypher panel for the learned remediation ordering"
        >
          Q-REM-1
        </button>
      ) : null}
    </p>
  );
}

function OptionList({
  options,
  history,
  exactId,
  busyId,
  chooseErr,
  onChoose,
  tenant,
}: {
  options: ActionOption[];
  /** Q-MEM-5 rows: how each fix kind fared on the recalled precedents. */
  history: FixHistoryRow[];
  exactId: string | null;
  busyId: string | null;
  chooseErr: { id: string; text: string } | null;
  onChoose: ((id: string) => void) | null;
  tenant: string;
}) {
  const now = useNow(60_000);
  return (
    <ul className="space-y-1.5" aria-label="Action options">
      {options.map((o, idx) => {
        const isChosen = o.id === exactId;
        const descId = `opt-${o.id}-why`;
        // M21: the learned why lines are shown on their own (moved line, guideline, suggestion), not inside the reason
        const learned = optionLearned(o);
        const moved = learned ? movedFrom(learned, idx + 1) !== null : false;
        const why = splitReason({
          ...o,
          reason: o.reason ? stripLearnedLines(o.reason, learned) : o.reason,
        });
        const fut = optionFuture(o);
        const ratio = why.learned ? workedRatio(o, why.learned) : null;
        const prefInDetails = !!learned?.preference?.line && !moved;
        return (
          <li
            key={o.id}
            className={cn(
              "rounded-lg px-3 py-2.5",
              !o.enabled
                ? "border border-dashed border-white/[0.08] text-zinc-400"
                : isChosen
                  ? "bg-sky-500/[0.07] ring-1 ring-sky-400/60"
                  : "bg-white/[0.02] ring-1 ring-white/[0.06]",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              {!o.enabled ? (
                <Ban aria-hidden className="size-3.5 text-[var(--fl-subtle)]" />
              ) : null}
              <span className="text-[10px] font-medium tracking-wider text-[var(--fl-subtle)] uppercase">
                {KIND_TEXT[o.kind] ?? o.kind}
              </span>
              <span
                className={cn(
                  "text-sm",
                  o.enabled
                    ? "font-semibold text-zinc-50"
                    : "text-zinc-400 line-through decoration-zinc-600",
                )}
              >
                {o.option}
              </span>
              {o.status === "rejected" ? (
                <StatusChip
                  tone="warn"
                  icon={ThumbsDown}
                  title={
                    o.rejected_at
                      ? `rejected ${new Date(o.rejected_at).toISOString()}`
                      : undefined
                  }
                >
                  rejected{o.rejected_by ? ` by ${o.rejected_by}` : ""}
                  {o.reject_reason ? `: ${o.reject_reason}` : ""}
                </StatusChip>
              ) : o.status === "failed" ? (
                <>
                  <StatusChip tone="warn" icon={CircleX}>
                    tried: did not take
                  </StatusChip>
                  {o.verdict ? <VerdictChip verdict={o.verdict} /> : null}
                </>
              ) : !o.enabled ? (
                <StatusChip tone="na" icon={Ban}>
                  not offered
                </StatusChip>
              ) : isChosen ? (
                <StatusChip tone="info" icon={Check}>
                  chosen
                </StatusChip>
              ) : null}
              {o.enabled && onChoose ? (
                <Button
                  size="sm"
                  variant={isChosen ? "outline" : "default"}
                  className="ml-auto"
                  disabled={busyId !== null}
                  onClick={() => onChoose(o.id)}
                  aria-describedby={descId}
                >
                  {busyId === o.id ? (
                    <LoaderCircle
                      aria-hidden
                      className="motion-safe:animate-spin"
                    />
                  ) : null}
                  {isChosen ? "Re-choose" : "Choose"}
                </Button>
              ) : null}
            </div>
            {learned ? <MovedLine learned={learned} place={idx + 1} /> : null}
            {learned?.guideline ? (
              <GuidelineBanner g={learned.guideline} tenant={tenant} now={now} />
            ) : null}
            {learned?.contract_suggestion && o.enabled ? (
              <SuggestionChip
                s={learned.contract_suggestion}
                tenant={tenant}
                className="mt-1.5"
              />
            ) : null}
            {(o.enabled && history.some((h) => h.kind === o.kind)) || fut ? (
              <div
                role="group"
                className="mt-1.5 flex flex-wrap gap-1"
                aria-label="Predicted outcome and how this fix kind fared on recalled precedents"
              >
                {fut ? (
                  <StatusChip
                    tone={FUTURE_TEXT[fut.predicted]?.tone ?? "na"}
                    icon={Telescope}
                    title={`its own GRAPH.COPY branch (${fut.key}), Q-FUTURE-1`}
                  >
                    {FUTURE_TEXT[fut.predicted]?.text ??
                      `predicted: ${fut.predicted}`}
                  </StatusChip>
                ) : null}
                {o.enabled
                  ? history
                      .filter((h) => h.kind === o.kind)
                      .map((h) => (
                        <FixHistoryChip key={`${h.kind}:${h.verdict}`} row={h} />
                      ))
                  : null}
              </div>
            ) : null}
            {why.base || why.learned || fut || prefInDetails || (o.enabled && o.preview && Object.keys(o.preview).length) ? (
              <Disclosure
                className="mt-1.5"
                size="xs"
                summary={o.enabled ? "Why and details" : "Why it is not offered"}
                defaultOpen={!o.enabled ? true : undefined}
              >
              <div id={descId} className="space-y-1">
                {why.base ? (
                  <p
                    className={cn(
                      "text-xs leading-relaxed break-words",
                      o.enabled ? "text-zinc-300" : "text-zinc-400",
                    )}
                  >
                    {why.base}
                  </p>
                ) : null}
                {fut ? (
                  <p className="text-xs leading-relaxed break-words text-zinc-400">
                    {fut.line}
                    {fut.exposed.length
                      ? `; leaves ${fut.exposed.join(", ")} exposed`
                      : ""}
                  </p>
                ) : null}
                {why.learned ? (
                  <p className="flex flex-wrap items-start gap-1.5 text-xs break-words text-zinc-300">
                    <StatusChip tone="na" icon={History}>
                      learned order{ratio ? ` ${ratio}` : ""}
                    </StatusChip>
                    <span className="min-w-0 flex-1">{why.learned}</span>
                  </p>
                ) : null}
                {prefInDetails && learned ? <PreferenceLine learned={learned} /> : null}
                {o.enabled && o.preview && Object.keys(o.preview).length ? (
                  <p className="font-mono text-[11px] break-all text-[var(--fl-subtle)]">
                    {Object.entries(o.preview)
                      .map(
                        ([k, v]) =>
                          `${k}: ${typeof v === "string" ? v : Array.isArray(v) ? v.join(", ") : JSON.stringify(v)}`,
                      )
                      .join(" · ")}
                  </p>
                ) : null}
              </div>
              </Disclosure>
            ) : null}
            {chooseErr?.id === o.id ? (
              <p role="alert" className="mt-1 text-xs text-red-300">
                Choose failed: {chooseErr.text}
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<"idle" | "ok" | "blocked">("idle");
  return (
    <>
      <Button
        size="xs"
        variant="outline"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setState("ok");
          } catch {
            setState("blocked");
          }
        }}
        aria-label={`Copy ${label}`}
      >
        {state === "ok" ? <Check aria-hidden /> : <Copy aria-hidden />}
        {state === "ok"
          ? "Copied"
          : state === "blocked"
            ? "Copy blocked"
            : "Copy"}
      </Button>
      <span className="sr-only" role="status">
        {state === "ok"
          ? `${label} copied`
          : state === "blocked"
            ? "Copy blocked by the browser"
            : ""}
      </span>
    </>
  );
}

function ExactActionView({ action }: { action: ExactAction }) {
  const repo =
    typeof action.args?.repo === "string" ? (action.args.repo as string) : null;
  const reviewers = Array.isArray(action.args?.reviewers)
    ? (action.args.reviewers as unknown[]).map(String)
    : [];
  return (
    <section
      aria-label="Exact action"
      className="space-y-2 rounded-md border border-sky-500/40 bg-zinc-950/60 p-2"
    >
      <h4 className="flex items-center gap-1.5 text-xs font-semibold text-sky-200">
        <FileDiff aria-hidden className="size-3.5" /> Exact action the server
        will take
      </h4>
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <dt className="text-zinc-400">kind</dt>
        <dd className="font-mono text-zinc-100">{action.kind}</dd>
        {repo ? (
          <>
            <dt className="text-zinc-400">repo</dt>
            <dd className="font-mono break-all text-zinc-100">{repo}</dd>
          </>
        ) : null}
        {reviewers.length ? (
          <>
            <dt className="text-zinc-400">reviewers</dt>
            <dd className="font-mono text-zinc-100">{reviewers.join(", ")}</dd>
          </>
        ) : null}
        <dt className="text-zinc-400">branch</dt>
        <dd className="flex items-center gap-1 font-mono break-all text-zinc-100">
          <GitBranch aria-hidden className="size-3 shrink-0 text-zinc-400" />
          {action.branch}
        </dd>
        {action.file ? (
          <>
            <dt className="text-zinc-400">file</dt>
            <dd className="font-mono text-zinc-100">{action.file}</dd>
          </>
        ) : null}
        <dt className="text-zinc-400">plan hash</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <code
            className="rounded bg-zinc-800 px-1 font-mono text-[12px] font-semibold text-zinc-50"
            title={action.plan_hash}
          >
            {action.plan_hash.slice(0, 12)}
          </code>
          <span className="text-[11px] text-zinc-400">
            (first 12 of {action.plan_hash.length})
          </span>
          <CopyButton text={action.plan_hash} label="plan hash" />
        </dd>
      </dl>

      {action.file &&
      typeof action.before === "string" &&
      typeof action.after === "string" ? (
        <DiffView
          file={action.file}
          before={action.before}
          after={action.after}
        />
      ) : null}

      {action.title ? (
        <div className="text-xs">
          <p className="text-zinc-400">issue title</p>
          <p className="text-zinc-100">{action.title}</p>
          {action.body ? (
            <pre
              tabIndex={0}
              role="region"
              aria-label="Issue body"
              className="mt-1 max-h-40 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] whitespace-pre-wrap text-zinc-200 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              {action.body}
            </pre>
          ) : null}
        </div>
      ) : null}

      {action.commit ? (
        <div className="text-xs">
          <p className="text-zinc-400">commit message</p>
          <pre className="mt-0.5 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] break-all whitespace-pre-wrap text-zinc-100">
            {action.commit}
          </pre>
        </div>
      ) : null}

      {action.pr_body ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-400 outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
            PR description the server will open
          </summary>
          <pre
            tabIndex={0}
            role="region"
            aria-label="PR description"
            className="mt-1 max-h-48 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-[11px] break-words whitespace-pre-wrap text-zinc-200 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            {action.pr_body}
          </pre>
        </details>
      ) : null}

      {action.rollback ? (
        <p className="flex items-start gap-1.5 text-xs text-zinc-200">
          <RotateCcw
            aria-hidden
            className="mt-0.5 size-3.5 shrink-0 text-zinc-400"
          />
          <span>
            <span className="text-zinc-400">rollback: </span>
            {action.rollback}
          </span>
        </p>
      ) : null}
    </section>
  );
}

function ApproveForm({
  incidentId,
  actionId,
  planHash,
  candidates,
  guideline = null,
  onRechoose,
  onApproved,
  onRejected,
}: {
  incidentId: string;
  actionId: string;
  planHash: string;
  /** Who-fixes ranking: the top person pre-fills the approver; all are offered as suggestions. */
  candidates: WhoFixesRow[];
  /** M21: the ACTIVE guideline this option is against (as the plan recorded it): approving needs an explicit override. */
  guideline?: OptionGuideline | null;
  onRechoose: () => void;
  onApproved: (res: ApproveResponse) => void;
  /** Called once /reject returns 200 (the option is disabled; the incident still awaits approval). */
  onRejected: (res: RejectResponse) => void;
}) {
  const tenant = useTenant();
  const inputId = useId();
  const keyId = useId();
  const listId = useId();
  const hintId = useId();
  const top = candidates[0] ?? null;
  const [approver, setApprover] = useState(top?.person ?? "");
  const match = candidates.find((c) => c.person === approver.trim()) ?? null;
  const [approverKey, setApproverKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{
    status: number | null;
    text: string;
    foreign: boolean;
    op: "approve" | "reject";
  } | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const reasonId = useId();
  const reasonHintId = useId();
  const rejectBtn = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const reasonOk = reason.trim().length >= 3;
  // M21: a guideline the server named when it refused the approval (promoted after the plan was made)
  const [refused, setRefused] = useState<{
    id: string;
    text: string | null;
    promotedBy: string | null;
  } | null>(null);
  const [overrideOn, setOverrideOn] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const override = refused
    ? refused
    : guideline
      ? {
          id: guideline.id,
          text: guideline.text,
          promotedBy: guideline.decided_by,
        }
      : null;
  const overrideOk =
    !override ||
    (overrideOn &&
      overrideReason.trim().length >= 3 &&
      overrideReason.trim().length <= 300);
  const overrideHintId = useId();

  const fail = (e: unknown, op: "approve" | "reject") => {
    const g =
      op === "approve" && e instanceof ApiError && e.status === 409
        ? guidelineFrom409(e.detail)
        : null;
    if (g) {
      // the server asks for an override: show it (never retried on the user's behalf)
      if (g.id !== override?.id) setOverrideOn(false);
      setRefused(g);
    }
    setErr({
      status: e instanceof ApiError ? e.status : null,
      text: e instanceof ApiError ? e.detail : errorText(e),
      foreign: isForeignRun(e),
      op,
    });
  };

  const reject = async () => {
    if (busy || !approver.trim() || !reasonOk) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await api.reject(
        incidentId,
        {
          action_id: actionId,
          plan_hash: planHash,
          approver: approver.trim(),
          reason: reason.trim(),
        },
        approverKey.trim() || undefined,
        tenant,
      );
      onRejected(res);
    } catch (e) {
      fail(e, "reject");
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await api.approve(
        incidentId,
        {
          action_id: actionId,
          plan_hash: planHash,
          approver: approver.trim(),
          ...(override
            ? {
                override_guideline: override.id,
                override_reason: overrideReason.trim(),
              }
            : {}),
        },
        approverKey.trim() || undefined,
        tenant,
      );
      onApproved(res);
    } catch (e) {
      fail(e, "approve");
      setBusy(false);
    }
  };

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy && approver.trim() && !rejecting && overrideOk) void approve();
      }}
    >
      {override ? (
        <OverrideFields
          guideline={override}
          refusedByServer={!!refused}
          checked={overrideOn}
          reason={overrideReason}
          onChecked={setOverrideOn}
          onReason={setOverrideReason}
          disabled={busy}
          hintId={overrideHintId}
        />
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-0.5">
          <label htmlFor={inputId} className="text-[11px] text-zinc-400">
            approver (unverified identity in demo mode)
          </label>
          <input
            id={inputId}
            value={approver}
            onChange={(e) => setApprover(e.target.value)}
            maxLength={60}
            required
            autoComplete="off"
            spellCheck={false}
            list={candidates.length ? listId : undefined}
            aria-describedby={hintId}
            placeholder="person id, e.g. from Who fixes it"
            className="h-8 w-40 rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          />
          {candidates.length ? (
            <datalist id={listId}>
              {candidates.map((c) => (
                <option key={c.person} value={c.person}>
                  {c.name ? `${c.name} (${c.person})` : c.person}
                </option>
              ))}
            </datalist>
          ) : null}
          <span id={hintId} className="text-[11px] text-zinc-300">
            {match ? (
              <>
                {match.name ?? match.person}{" "}
                <span className="font-mono text-zinc-400">
                  ({match.person})
                </span>
                {match === top
                  ? " · top of Who fixes it"
                  : " · ranked in Who fixes it"}
              </>
            ) : approver.trim() ? (
              "not in the Who fixes it ranking; the server checks the id is an active person in the graph"
            ) : top ? null : (
              "no ranked person recorded; enter an active person id"
            )}
          </span>
        </div>
        <Button
          type="submit"
          size="lg"
          disabled={busy || !approver.trim() || rejecting || !overrideOk}
          aria-describedby={override ? overrideHintId : undefined}
          className="bg-emerald-700 text-white hover:bg-emerald-800"
        >
          {busy && !rejecting ? (
            <LoaderCircle aria-hidden className="motion-safe:animate-spin" />
          ) : (
            <Stamp aria-hidden />
          )}
          Approve this exact action
        </Button>
        <Button
          ref={rejectBtn}
          type="button"
          size="lg"
          variant="outline"
          disabled={busy}
          aria-expanded={rejecting}
          aria-controls={reasonId}
          onClick={() => {
            setRejecting((r) => !r);
            setErr(null);
            if (!rejecting)
              requestAnimationFrame(() => reasonRef.current?.focus());
          }}
          className="border-amber-400/70 text-amber-100 hover:bg-amber-500/15"
        >
          <ThumbsDown aria-hidden />
          Reject…
        </Button>
      </div>
      {rejecting ? (
        <fieldset className="space-y-1.5 rounded-md border border-amber-400/50 bg-amber-500/5 p-2">
          <legend className="px-1 text-[11px] font-semibold text-amber-100">
            Reject this exact action
          </legend>
          <label htmlFor={reasonId} className="block text-[11px] text-zinc-300">
            Reason (required, at least 3 characters; recorded in the graph with
            the approver and time)
          </label>
          <textarea
            id={reasonId}
            ref={reasonRef}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                setRejecting(false);
                requestAnimationFrame(() => rejectBtn.current?.focus());
              }
            }}
            rows={2}
            maxLength={500}
            required
            aria-describedby={reasonHintId}
            aria-invalid={reason.length > 0 && !reasonOk ? true : undefined}
            placeholder="e.g. prefer a rollback during the release freeze"
            className="w-full rounded-md border border-zinc-600 bg-zinc-950 p-2 text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          />
          <p id={reasonHintId} className="text-[11px] text-zinc-300">
            The option is disabled for good and the incident stays awaiting
            approval, so you can choose another option. Nothing is changed
            outside the graph. Approver:{" "}
            <span className="font-mono">
              {approver.trim() || "(enter above)"}
            </span>
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={busy || !reasonOk || !approver.trim()}
              onClick={() => void reject()}
              className="bg-amber-300 text-zinc-950 hover:bg-amber-200"
            >
              {busy ? (
                <LoaderCircle
                  aria-hidden
                  className="motion-safe:animate-spin"
                />
              ) : (
                <ThumbsDown aria-hidden />
              )}
              Confirm reject
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setRejecting(false);
                requestAnimationFrame(() => rejectBtn.current?.focus());
              }}
            >
              Cancel
            </Button>
          </div>
        </fieldset>
      ) : null}
      <details
        open={err?.status === 403 || undefined}
        className="text-[11px] text-zinc-400"
      >
        <summary className="cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
          Approver key (only when the server acts on real GitHub)
        </summary>
        <div className="mt-1 flex flex-col gap-0.5">
          <label htmlFor={keyId}>
            X-Faultline-Approver-Key (sent with this approval only, never
            stored)
          </label>
          <input
            id={keyId}
            type="password"
            value={approverKey}
            onChange={(e) => setApproverKey(e.target.value)}
            autoComplete="off"
            className="h-7 w-64 rounded-md border border-zinc-600 bg-zinc-950 px-2 font-mono text-xs text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          />
        </div>
      </details>
      <p className="text-[11px] text-zinc-400">
        Approval is bound to plan hash{" "}
        <span className="font-mono text-zinc-300">{planHash.slice(0, 12)}</span>
        : if the plan changes, the server refuses it (409).
      </p>
      {err ? (
        <div
          role="alert"
          className="flex flex-wrap items-start gap-2 rounded-md border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-100"
        >
          <OctagonAlert
            aria-hidden
            className="mt-0.5 size-4 shrink-0 text-red-300"
          />
          <p className="min-w-0 flex-1">
            {err.foreign ? (
              <>
                <strong className="font-semibold">Not your run.</strong>{" "}
                {FOREIGN_RUN_TEXT}
              </>
            ) : err.status === 409 &&
              err.op === "approve" &&
              guidelineFrom409(err.text) ? (
              <>
                <strong className="font-semibold">
                  Needs a guideline override:
                </strong>{" "}
                {err.text} (HTTP 409). Tick the override above and give a
                reason, then approve again.
              </>
            ) : err.status === 409 ? (
              <>
                <strong className="font-semibold">
                  Plan changed: re-choose.
                </strong>{" "}
                {err.text} (HTTP 409)
              </>
            ) : err.status === 422 &&
              err.op === "reject" &&
              !/approver/i.test(err.text) ? (
              <>
                <strong className="font-semibold">Reason needed:</strong>{" "}
                {err.text} (HTTP 422).
              </>
            ) : err.status === 422 && /approver/i.test(err.text) ? (
              <>
                <strong className="font-semibold">
                  Approver not recognised:
                </strong>{" "}
                {err.text} (HTTP 422). Pick someone from Who fixes it.
              </>
            ) : err.status === 403 ? (
              <>
                <strong className="font-semibold">
                  Approver key required:
                </strong>{" "}
                {err.text} (HTTP 403). The server acts on real GitHub; enter the
                approver key above.
              </>
            ) : err.status === 429 ? (
              <>
                <strong className="font-semibold">Rate limited:</strong>{" "}
                {err.text} (HTTP 429). Try again in a minute.
              </>
            ) : (
              <>
                <strong className="font-semibold">
                  {err.op === "reject" ? "Reject failed:" : "Approval failed:"}
                </strong>{" "}
                {err.text}
                {err.status ? ` (HTTP ${err.status})` : ""}
              </>
            )}
          </p>
          {err.status === 409 && !guidelineFrom409(err.text) ? (
            <Button size="xs" variant="outline" onClick={onRechoose}>
              <RotateCcw aria-hidden /> Re-choose
            </Button>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}

export function VerdictChip({
  verdict,
  large,
}: {
  verdict: Verdict;
  large?: boolean;
}) {
  const m = VERDICT_META[verdict];
  const Icon = m.icon;
  return (
    <span
      title={m.meaning}
      data-verdict={verdict}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border font-bold tracking-wide",
        large ? "px-2.5 py-1 text-base" : "px-1.5 py-0.5 text-[11px]",
        m.cls,
      )}
    >
      <Icon aria-hidden className={large ? "size-5" : "size-3.5"} />
      <span aria-hidden>{m.glyph}</span>
      {m.text}
    </span>
  );
}

function ActionOutcome({
  option,
  stages,
  plan,
  approvedBy,
  extra = null,
  paged = true,
}: {
  option: ActionOption;
  stages: StageRow[];
  plan: PlanResponse;
  /** The approver as the server checked it in the graph (this session's approval only). */
  approvedBy: ApproveResponse["approver"] | null;
  /** M21: the guideline override this session's approval carried, and whether the approval was learned. */
  extra?: Pick<ApproveResponse, "override" | "learned"> | null;
  /** M19: a live run pages the on-call when an approved fix ends unresolved; a replay recording predates paging. */
  paged?: boolean;
}) {
  const pageNote = paged ? "the on-call was paged" : "no page sent in this recording";
  const sorted = [...stages].sort((a, b) => a.at - b.at || a.ord - b.ord);
  const byStage = new Map<string, StageRow>();
  for (const st of sorted) byStage.set(st.stage, st);
  const final =
    byStage.get("RESOLVED") ??
    byStage.get("UNKNOWN_ESCALATED") ??
    byStage.get("FAILED") ??
    null;
  // Steps = the stages actually recorded after AWAITING_APPROVAL (in order), then the expected ones not reached yet.
  const pausedAt = sorted.findIndex((st) => st.stage === "AWAITING_APPROVAL");
  const recorded = (
    pausedAt >= 0
      ? sorted.slice(pausedAt + 1)
      : sorted.filter((st) => POST_STEPS.includes(st.stage as never))
  )
    .map((st) => st.stage)
    .filter((st, i, arr) => arr.indexOf(st) === i);
  const steps: string[] = final
    ? recorded
    : [
        ...recorded,
        ...[...POST_STEPS, "RESOLVED"].filter((st) => !recorded.includes(st)),
      ];
  const reached = steps.map((st) => byStage.has(st));
  const current = final ? -1 : reached.lastIndexOf(true) + 1;
  const missingExpected = final
    ? POST_STEPS.filter((st) => !byStage.has(st))
    : [];
  const wb = parseVerified(final?.note ?? "");
  const tracked =
    option.kind === "open_issue" &&
    option.verdict === "APPLIED" &&
    final?.stage === "UNKNOWN_ESCALATED";
  const partial = wb !== null && wb.n < wb.m;
  const top = plan.who_fixes?.payload?.rows?.[0] ?? null;
  const ref = parseRef(option.external_ref);
  const ch = option.channels;
  const spec = option.spec;

  // Polite live summary of the step progress for screen readers.
  const summary = final
    ? `${final.stage}${final.note ? `: ${final.note}` : ""}`
    : option.verdict
      ? `verdict ${option.verdict}`
      : `${steps[Math.max(0, current - 1)] ?? "approved"}`;

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-zinc-700 p-2">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <StatusChip tone="pass" icon={Stamp}>
            approved
          </StatusChip>
          <span className="font-semibold text-zinc-50">{option.option}</span>
        </p>
        <dl className="mt-1 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[11px]">
          {option.plan_hash ? (
            <>
              <dt className="text-zinc-400">plan hash</dt>
              <dd className="font-mono text-zinc-200" title={option.plan_hash}>
                {option.plan_hash.slice(0, 12)}
              </dd>
            </>
          ) : null}
          {option.approval_id ? (
            <>
              <dt className="text-zinc-400">approval</dt>
              <dd className="font-mono break-all text-zinc-200">
                {option.approval_id}
              </dd>
            </>
          ) : null}
          {spec?.branch ? (
            <>
              <dt className="text-zinc-400">branch</dt>
              <dd className="font-mono break-all text-zinc-200">
                {spec.branch}
              </dd>
            </>
          ) : null}
          {spec?.diff ? (
            <>
              <dt className="text-zinc-400">patch</dt>
              <dd className="min-w-0">
                <pre
                  className="max-h-56 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 text-[11px] leading-snug text-zinc-200"
                  aria-label="the exact diff that will be applied"
                >
                  {spec.diff}
                </pre>
                {spec.reasoning ? (
                  <p className="mt-1 text-xs text-zinc-400">{spec.reasoning}</p>
                ) : null}
              </dd>
            </>
          ) : null}
          {approvedBy ? (
            <>
              <dt className="text-zinc-400">approver</dt>
              <dd className="text-zinc-200">
                {approvedBy.name ?? approvedBy.id}{" "}
                <span className="font-mono text-zinc-400">
                  ({approvedBy.id})
                </span>
                {" · active person in the graph"}
                {approvedBy.owner_team ? " · on the owning team" : ""}
                {approvedBy.committed
                  ? " · has committed to the component"
                  : ""}
              </dd>
            </>
          ) : null}
          {extra?.override ? (
            <>
              <dt className="text-zinc-400">override</dt>
              <dd className="break-words text-amber-100">
                <ShieldAlert
                  aria-hidden
                  className="mr-1 inline size-3 align-[-2px] text-amber-300"
                />
                guideline{" "}
                <span className="font-mono">{extra.override.id}</span>{" "}
                (&ldquo;{extra.override.text}&rdquo;) overridden:{" "}
                <span className="text-zinc-200">
                  &ldquo;{extra.override.reason}&rdquo;
                </span>
              </dd>
            </>
          ) : null}
          {extra?.learned ? (
            <>
              <dt className="text-zinc-400">learned</dt>
              <dd className="break-words text-zinc-300">
                {extra.learned.learned ? (
                  <>
                    recorded as{" "}
                    <span className="font-mono">{extra.learned.event}</span> for{" "}
                    {extra.learned.family}
                  </>
                ) : (
                  <>not learned: {extra.learned.why}</>
                )}
              </dd>
            </>
          ) : null}
        </dl>
      </div>

      <ol className="space-y-1" aria-label="Action path after approval">
        {steps.map((s, i) => {
          const row = byStage.get(s);
          const isCurrent = i === current;
          const bad = s === "UNKNOWN_ESCALATED" || s === "FAILED";
          return (
            <li key={s} className="flex items-start gap-2 text-xs">
              {row ? (
                bad ? (
                  <CircleX
                    aria-hidden
                    className="mt-0.5 size-4 shrink-0 text-red-300"
                  />
                ) : (
                  <CircleCheck
                    aria-hidden
                    className="mt-0.5 size-4 shrink-0 text-emerald-300"
                  />
                )
              ) : isCurrent ? (
                <LoaderCircle
                  aria-hidden
                  className="mt-0.5 size-4 shrink-0 text-sky-300 motion-safe:animate-spin"
                />
              ) : (
                <CircleDashed
                  aria-hidden
                  className="mt-0.5 size-4 shrink-0 text-[var(--fl-subtle)]"
                />
              )}
              <span className="min-w-0">
                <span
                  className={cn(
                    "font-mono font-semibold",
                    row ? "text-zinc-50" : "text-zinc-400",
                  )}
                >
                  {s}
                </span>{" "}
                <span className="text-zinc-400">
                  {row ? "done" : isCurrent ? "in progress" : "pending"}
                </span>
                {row?.note ? (
                  <span className="block break-words text-zinc-300">
                    {row.note}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="sr-only" aria-live="polite">
        {summary}
      </p>

      {option.verdict ? (
        <div className="space-y-2 rounded-md border border-zinc-700 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-zinc-400">verdict</span>
            <VerdictChip verdict={option.verdict} large />
            {option.kind === "open_issue" && option.verdict === "APPLIED" ? (
              <StatusChip tone="info" icon={Ticket}>
                tracked in issue
              </StatusChip>
            ) : null}
            {option.verdict === "UNKNOWN" ||
            (option.verdict === "NOT_APPLIED" &&
              final?.stage === "UNKNOWN_ESCALATED") ? (
              <span className="text-sm font-semibold text-red-200">
                Suggested escalation:{" "}
                {top
                  ? `${top.name ?? top.person} (${top.person})`
                  : "a human (no ranked person recorded)"}{" "}
                <span className="font-normal text-red-100">({pageNote})</span>
              </span>
            ) : null}
          </div>
          {option.explanation ? (
            <p className="text-xs text-zinc-200">{option.explanation}</p>
          ) : null}
          {ch ? (
            <ul
              className="space-y-1 text-xs"
              aria-label="Verification channels"
            >
              {ch.github_main ? (
                <Channel
                  ok={ch.github_main.ok}
                  title="GitHub main HEAD"
                  text={
                    ch.github_main.ok
                      ? "has the change"
                      : (ch.github_main.detail ?? "does not have the change")
                  }
                  extra={
                    ch.github_main.served_by
                      ? `served by ${ch.github_main.served_by}`
                      : null
                  }
                />
              ) : null}
              {ch.telemetry ? <TelemetryRows t={ch.telemetry} /> : null}
            </ul>
          ) : null}
          {ref ? (
            <p className="flex flex-wrap items-center gap-1.5 text-xs">
              <GitPullRequest
                aria-hidden
                className="size-3.5 text-zinc-400"
              />
              <span className="text-zinc-400">PR</span>
              {ref.simulated ? (
                <>
                  <span className="font-mono break-all text-zinc-100">
                    {ref.url}
                  </span>
                  <StatusChip
                    tone="na"
                    title="keyless mode: the simulated GitHub recorded this PR; nothing was opened on github.com"
                  >
                    (simulated)
                  </StatusChip>
                </>
              ) : (
                <a
                  href={ref.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 font-mono break-all text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  {ref.url} <ExternalLink aria-hidden className="size-3" />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              )}
            </p>
          ) : null}
        </div>
      ) : null}

      {missingExpected.length ? (
        <p
          role="note"
          className="flex items-center gap-1 text-xs text-amber-300"
        >
          <CircleHelp aria-hidden className="size-3.5" /> No stage event
          recorded for {missingExpected.join(", ")}.
        </p>
      ) : null}
      {final ? (
        partial ? (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-lg border-2 border-amber-400 bg-amber-500/15 p-3"
          >
            <OctagonAlert
              aria-hidden
              className="size-7 shrink-0 text-amber-300"
            />
            <div>
              <p className="text-[11px] font-semibold tracking-wide text-amber-300 uppercase">
                {final.stage === "RESOLVED"
                  ? "Resolved, but write-back not fully verified"
                  : `Write-back not fully verified: handed to a human (${pageNote})`}
              </p>
              <p className="text-lg font-bold text-amber-50">{final.note}</p>
              <p className="text-xs text-amber-100">
                {wb!.m - wb!.n} of {wb!.m} write-back checks did not verify on
                the read-back.
              </p>
            </div>
          </div>
        ) : tracked ? (
          <div
            role="status"
            className="flex items-center gap-2 rounded-lg border-2 border-sky-400 bg-sky-500/15 p-3"
          >
            <Ticket aria-hidden className="size-7 shrink-0 text-sky-300" />
            <div>
              <p className="text-[11px] font-semibold tracking-wide text-sky-300 uppercase">
                Tracked in issue
              </p>
              <p className="text-base font-bold text-sky-50">
                Handed to humans: the incident is not resolved
              </p>
              <p className="text-xs text-sky-100">
                Opening the issue was verified; it changes nothing in
                production, so there is no postmortem.
                {final.note ? ` ${final.note}` : ""}
              </p>
            </div>
          </div>
        ) : final.stage === "RESOLVED" ? (
          <div
            role="status"
            className="flex items-center gap-2 rounded-lg border-2 border-emerald-400 bg-emerald-500/15 p-3"
          >
            <ShieldCheck
              aria-hidden
              className="size-7 shrink-0 text-emerald-300"
            />
            <div>
              <p className="text-[11px] font-semibold tracking-wide text-emerald-300 uppercase">
                Resolved
              </p>
              <p className="text-lg font-bold text-emerald-50">
                {final.note || "resolved"}
              </p>
            </div>
          </div>
        ) : (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-lg border-2 border-red-400 bg-red-500/15 p-3"
          >
            <OctagonAlert
              aria-hidden
              className="size-7 shrink-0 text-red-300"
            />
            <div>
              <p className="text-[11px] font-semibold tracking-wide text-red-300 uppercase">
                {final.stage === "FAILED"
                  ? "Action failed"
                  : `Unknown: handed to a human (${pageNote})`}
              </p>
              <p className="text-sm font-semibold break-words text-red-50">
                {final.note || final.stage}
              </p>
            </div>
          </div>
        )
      ) : null}
    </div>
  );
}

function Channel({
  ok,
  title,
  text,
  extra,
}: {
  ok: boolean | null;
  title: string;
  text: string;
  extra: string | null;
}) {
  return (
    <li className="flex items-start gap-1.5">
      {ok === true ? (
        <CircleCheck
          aria-hidden
          className="mt-0.5 size-3.5 shrink-0 text-emerald-300"
        />
      ) : ok === false ? (
        <CircleX
          aria-hidden
          className="mt-0.5 size-3.5 shrink-0 text-red-300"
        />
      ) : (
        <CircleHelp
          aria-hidden
          className="mt-0.5 size-3.5 shrink-0 text-amber-300"
        />
      )}
      <span className="min-w-0">
        <span className="font-semibold text-zinc-100">{title}</span>{" "}
        <span
          className={
            ok === true
              ? "text-emerald-200"
              : ok === false
                ? "text-red-200"
                : "text-amber-200"
          }
        >
          {ok === true ? "ok" : ok === false ? "failed" : "unknown"}
        </span>
        <span className="text-zinc-300">: {text}</span>
        {extra ? (
          <span className="block text-[11px] text-zinc-400">{extra}</span>
        ) : null}
      </span>
    </li>
  );
}

function fmtList(v: number[] | undefined): string {
  return v && v.length
    ? v.map((x) => fmtValue(x)).join(", ")
    : "– (not recorded)";
}

/** One row per checked telemetry target: symptoms vs baseline × band, protected nodes for collateral. */
function TelemetryRows({ t }: { t: TelemetryChannel }) {
  const targets = t.targets
    ? Object.entries(t.targets).sort(
        ([a, x], [b, y]) =>
          Number(!!x.collateral) - Number(!!y.collateral) || a.localeCompare(b),
      )
    : null;
  if (!targets) {
    // Older single-target shape.
    const base = typeof t.baseline === "number" ? t.baseline : null;
    const band = typeof t.band === "number" ? t.band : null;
    const text =
      !t.after?.length && base === null && band === null
        ? "no telemetry values recorded on the action"
        : `after ${fmtList(t.after)} vs baseline ${fmtValue(base)} × band ${fmtValue(band)}${base !== null && band !== null ? ` (= ${fmtValue(base * band)})` : ""}`;
    return <Channel ok={t.ok} title="Telemetry" text={text} extra={null} />;
  }
  return (
    <li>
      <span className="flex items-center gap-1.5">
        <ChannelIcon ok={t.ok} />
        <span className="font-semibold text-zinc-100">Telemetry</span>
        <OkWord ok={t.ok} />
        <span className="text-zinc-400">
          · {targets.length} target{targets.length === 1 ? "" : "s"} checked
        </span>
      </span>
      <ul className="mt-0.5 space-y-0.5 pl-5" aria-label="Telemetry per target">
        {targets.map(([node, x]) => {
          let text: string;
          if (x.ok === null && x.note) text = x.note;
          else if (typeof x.before_action_max === "number")
            text = `after ${fmtList(x.after)} vs max before the action ${fmtValue(x.before_action_max)}`;
          else {
            const base = typeof x.baseline === "number" ? x.baseline : null;
            const band = typeof x.band === "number" ? x.band : null;
            text = `after ${fmtList(x.after)} vs baseline ${fmtValue(base)} × band ${fmtValue(band)}${base !== null && band !== null ? ` (= ${fmtValue(base * band)})` : ""}`;
          }
          return (
            <li key={node} className="flex items-start gap-1.5">
              <ChannelIcon ok={x.ok} small />
              <span className="min-w-0">
                <span className="font-mono text-zinc-100">{node}</span>{" "}
                <span className="text-zinc-400">
                  ({x.collateral ? "protected: collateral check" : "symptom"})
                </span>{" "}
                <OkWord ok={x.ok} />
                <span className="text-zinc-300">: {text}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </li>
  );
}

function ChannelIcon({ ok, small }: { ok: boolean | null; small?: boolean }) {
  const cls = cn("mt-0.5 shrink-0", small ? "size-3" : "size-3.5");
  return ok === true ? (
    <CircleCheck aria-hidden className={cn(cls, "text-emerald-300")} />
  ) : ok === false ? (
    <CircleX aria-hidden className={cn(cls, "text-red-300")} />
  ) : (
    <CircleHelp aria-hidden className={cn(cls, "text-amber-300")} />
  );
}

function OkWord({ ok }: { ok: boolean | null }) {
  return (
    <span
      className={
        ok === true
          ? "text-emerald-200"
          : ok === false
            ? "text-red-200"
            : "text-amber-200"
      }
    >
      {ok === true ? "ok" : ok === false ? "failed" : "no signal"}
    </span>
  );
}

/** Options that were approved but did not take (NOT_APPLIED): the run came back for a new choice. */
function FailedAttempts({
  failed,
  note,
}: {
  failed: ActionOption[];
  note: string | null;
}) {
  return (
    <div
      role="note"
      className="space-y-1.5 rounded-md border border-amber-400/60 bg-amber-500/10 p-2 text-xs text-amber-50"
    >
      <p className="flex items-center gap-1.5 font-semibold">
        <RotateCcw aria-hidden className="size-3.5 text-amber-300" />
        Back to approval: a previous fix did not take
      </p>
      {note ? <p className="text-amber-100">{note}</p> : null}
      <ul className="space-y-1.5">
        {failed.map((o) => (
          <li key={o.id} className="rounded border border-amber-400/30 p-1.5">
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="font-semibold">{o.option}</span>
              {o.verdict ? <VerdictChip verdict={o.verdict} /> : null}
            </p>
            {o.explanation ? (
              <p className="mt-0.5 text-amber-100">{o.explanation}</p>
            ) : null}
            {o.channels ? (
              <ul
                className="mt-1 space-y-1"
                aria-label={`Verification channels for ${o.option}`}
              >
                {o.channels.github_main ? (
                  <Channel
                    ok={o.channels.github_main.ok}
                    title="GitHub main HEAD"
                    text={
                      o.channels.github_main.ok
                        ? "has the change"
                        : (o.channels.github_main.detail ??
                          "does not have the change")
                    }
                    extra={null}
                  />
                ) : null}
                {o.channels.telemetry ? (
                  <TelemetryRows t={o.channels.telemetry} />
                ) : null}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "write-back verified 7/7" → {n: 7, m: 7}. */
function parseVerified(note: string): { n: number; m: number } | null {
  const m = note.match(/verified\s+(\d+)\s*\/\s*(\d+)/);
  return m ? { n: Number(m[1]), m: Number(m[2]) } : null;
}

function parseRef(
  ref: string | null,
): { url: string; simulated: boolean } | null {
  if (!ref) return null;
  const simulated = /\(simulated\)\s*$/.test(ref);
  return { url: ref.replace(/\s*\(simulated\)\s*$/, ""), simulated };
}
