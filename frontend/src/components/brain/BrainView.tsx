"use client";

import { Fragment, useId, useState, useSyncExternalStore } from "react";
import {
  ArrowDown,
  BrainCircuit,
  CircleAlert,
  ExternalLink,
  HeartPulse,
  History,
  LoaderCircle,
  MessageSquareText,
  Send,
  ShieldCheck,
  ShieldX,
  Wand2,
} from "lucide-react";
import { api, ApiError, brainUserId, errorText } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { fmtMs } from "@/lib/format";
import type { BrainAnswer, BrainStep, LlmMode } from "@/lib/types";
import { useAppStatus } from "@/components/AppShell";
import { useCypherPanel } from "@/components/cypher/CypherPanelContext";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/StatusChip";
import { cn, safeHttpUrl } from "@/lib/utils";
import { AnswerGraph } from "./AnswerGraph";
import { BrainHistory } from "./BrainHistory";
import { BrainWidgets } from "./BrainWidgets";
import { ForgetPanel } from "./ForgetPanel";

const noSubscribe = () => () => {};

const EXAMPLES = [
  "Who on the team has worked on payment before?",
  "What did we decide about payment timeouts, and is it still current?",
  "Which revenue-path services lack a runbook or owner?",
  "What breaks if productcatalog goes down?",
  "What breaks if recommendation goes down?",
];

/** Company brain over time (M12): ownership history, as-of beliefs, component timelines, knowledge health. */
const TIME_EXAMPLES = [
  "Who owned fraud-detection during inc-h002?",
  "What did we know about product-catalog as of 2025-11-01?",
  "What is the history of fraud-detection?",
  "Where is our knowledge stale?",
];

/**
 * Examples name components of the seeded demo tenants, so they follow the top-bar tenant (each was checked to
 * answer with the citation guard passing). Any other tenant gets only the questions that name no component.
 */
const EXAMPLES_BY_TENANT: Record<string, { now: string[]; time: string[] }> = {
  acme: { now: EXAMPLES, time: TIME_EXAMPLES },
  globex: {
    now: [
      "Who on the team has worked on card-gateway before?",
      "What did we decide about card gateway timeouts, and is it still current?",
      "Which revenue-path services lack a runbook or owner?",
      "What breaks if session-service goes down?",
    ],
    time: ["Who owned legacy-cache during gx-inc-001?", "What is the history of session-service?", "Where is our knowledge stale?"],
  },
};
const GENERIC_EXAMPLES = { now: ["Which revenue-path services lack a runbook or owner?"], time: ["Where is our knowledge stale?"] };

const KNOWLEDGE_HEALTH_QUESTION = "Where is our knowledge stale?";

const TIER_TEXT: Record<number, string> = {
  1: "tier 1: entity lookup (id / full-text)",
  2: "tier 2: Cypher templates",
  3: "tier 3: guarded text2cypher",
};

/** Wall clock for "$now" in Q-CTX-1 (on-call right now); only called from click handlers. */
function nowMs(): number {
  return Date.now();
}

const T2C_REASON =
  "text2cypher: this query was generated for this question and passed the guard; it is not a catalogue template, so PROFILE / Re-run are not offered here.";

/**
 * Company brain (T3): ask a question, get an answer whose every [id] passed the citation guard
 * (seen by a tool call of this question's run). The "via" chain lists each graph step; each
 * opens the Cypher panel. Errors (422 / 429 / 503) are shown inline; 503 also raises the banner.
 */
export function BrainView() {
  const tenant = useTenant();
  const examples = EXAMPLES_BY_TENANT[tenant] ?? GENERIC_EXAMPLES;
  const status = useAppStatus();
  const llmConfigured = status.status?.llm_configured === true;
  const inputId = useId();
  const [question, setQuestion] = useState("");
  const [llm, setLlm] = useState<LlmMode>("baseline");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<BrainAnswer | null>(null);
  const [err, setErr] = useState<{ status: number | null; text: string } | null>(null);
  const effectiveLlm: LlmMode = llm === "anthropic" && !llmConfigured ? "baseline" : llm;
  // Anonymous per-tab id (sessionStorage) so the graph can keep this visitor's history; null on the server.
  const user = useSyncExternalStore(noSubscribe, brainUserId, () => null);

  const ask = async (q: string) => {
    const text = q.trim();
    if (text.length < 3 || busy) return;
    setQuestion(text);
    setBusy(true);
    setErr(null);
    try {
      setAnswer(await api.brainAsk(text, effectiveLlm, user, tenant));
    } catch (e) {
      setErr({ status: e instanceof ApiError ? e.status : null, text: e instanceof ApiError ? e.detail : errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid w-full max-w-[1400px] gap-4 p-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-4 self-start">
        <section aria-labelledby="brain-ask-h" className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <h1 id="brain-ask-h" className="flex items-center gap-2 text-lg font-semibold text-zinc-50">
            <BrainCircuit aria-hidden className="size-5 text-violet-300" /> Company brain
          </h1>
          <p className="text-sm text-zinc-300">
            Who owns, knows and decided what, answered from the tenant graph. Every id in the answer was seen by a graph
            query of this question (citation guard).
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(question);
            }}
            className="space-y-2"
          >
            <label htmlFor={inputId} className="text-xs text-zinc-400">
              Question
            </label>
            <textarea
              id={inputId}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask(question);
                }
              }}
              rows={3}
              maxLength={500}
              placeholder={`e.g. ${examples.now[0]}`}
              className="w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-50 outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            <div className="flex flex-wrap items-center gap-2">
              <div role="radiogroup" aria-label="Answered by" className="flex overflow-hidden rounded-md border border-zinc-700 text-xs">
                <button
                  type="button"
                  role="radio"
                  aria-checked={effectiveLlm === "baseline"}
                  onClick={() => setLlm("baseline")}
                  className={cn(
                    "px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-inset",
                    effectiveLlm === "baseline" ? "bg-sky-500/20 text-sky-100" : "text-zinc-300 hover:bg-zinc-800",
                  )}
                >
                  Baseline (no LLM)
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={effectiveLlm === "anthropic"}
                  aria-disabled={!llmConfigured || undefined}
                  onClick={() => llmConfigured && setLlm("anthropic")}
                  title={llmConfigured ? undefined : "ANTHROPIC_API_KEY is not configured on the server"}
                  className={cn(
                    "px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-inset",
                    effectiveLlm === "anthropic" ? "bg-sky-500/20 text-sky-100" : "text-zinc-300 hover:bg-zinc-800",
                    !llmConfigured && "text-zinc-500 hover:bg-transparent",
                  )}
                >
                  Anthropic{llmConfigured ? "" : " (not configured)"}
                </button>
              </div>
              <Button type="submit" className="ml-auto" disabled={busy || question.trim().length < 3}>
                {busy ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <Send aria-hidden />}
                Ask
              </Button>
            </div>
          </form>
          <ExampleList title="Examples" questions={examples.now} icon={MessageSquareText} busy={busy} onAsk={(q) => void ask(q)} />
          <ExampleList
            title="Over time (ownership, as-of, history)"
            questions={examples.time}
            icon={History}
            busy={busy}
            onAsk={(q) => void ask(q)}
          />
        </section>
        <KnowledgeHealthPanel busy={busy} onCheck={() => void ask(KNOWLEDGE_HEALTH_QUESTION)} answer={answer} />
        <BrainHistory user={user} refreshKey={answer?.run_id ?? ""} onAsk={(q) => void ask(q)} busy={busy} />
        <ForgetPanel />
      </div>

      <section aria-labelledby="brain-answer-h" aria-busy={busy} className="space-y-3 self-start">
        <h2 id="brain-answer-h" className="sr-only">
          Answer
        </h2>
        <div aria-live="polite">
          {err ? (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
              <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-red-300" />
              <p>
                <strong className="font-semibold">
                  {err.status === 403
                    ? "Live LLM not available here:"
                    : err.status === 422
                    ? "Question not accepted:"
                    : err.status === 429
                      ? "Rate limited:"
                      : err.status === 503
                        ? "Brain unavailable:"
                        : "Ask failed:"}
                </strong>{" "}
                {err.text}
                {err.status ? ` (HTTP ${err.status})` : ""}
                {err.status === 429 ? " Try again in a minute." : ""}
                {err.status === 403 ? " Switch to Baseline: it answers from Cypher templates with no key." : ""}
              </p>
            </div>
          ) : busy ? (
            <p className="text-sm text-zinc-300">Asking the graph…</p>
          ) : !answer ? (
            <p className="rounded-lg border border-dashed border-zinc-700 p-4 text-sm text-zinc-300">
              Ask a question or pick an example. The answer, its citations and the graph queries behind it appear here.
            </p>
          ) : (
            <AnswerView a={answer} />
          )}
        </div>
      </section>
      <div className="lg:col-span-2">
        <BrainWidgets />
      </div>
    </div>
  );
}

function ExampleList({
  title,
  questions,
  icon: Icon,
  busy,
  onAsk,
}: {
  title: string;
  questions: string[];
  icon: typeof MessageSquareText;
  busy: boolean;
  onAsk: (q: string) => void;
}) {
  return (
    <div>
      <h2 className="mb-1 text-xs font-semibold tracking-wide text-zinc-400 uppercase">{title}</h2>
      <ul className="flex flex-col gap-1.5">
        {questions.map((q) => (
          <li key={q}>
            <button
              type="button"
              onClick={() => onAsk(q)}
              disabled={busy}
              className="flex w-full items-start gap-1.5 rounded-md border border-zinc-700 px-2 py-1.5 text-left text-sm text-zinc-200 outline-none hover:bg-zinc-800 focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
            >
              <Icon aria-hidden className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Knowledge health: asks the brain "Where is our knowledge stale?" through the same
 * /api/brain/ask endpoint (intent `knowledge`: stale runbooks and docs by reviewed_at,
 * handovers without a fresh runbook, decisions contradicted by recent changes). Nothing runs
 * on page load; the answer, with its citation guard and Cypher steps, appears in the answer pane.
 */
function KnowledgeHealthPanel({ busy, onCheck, answer }: { busy: boolean; onCheck: () => void; answer: BrainAnswer | null }) {
  const last = answer && answer.question === KNOWLEDGE_HEALTH_QUESTION ? answer : null;
  return (
    <section aria-labelledby="khealth-h" className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 id="khealth-h" className="flex items-center gap-1.5 text-sm font-semibold text-zinc-50">
        <HeartPulse aria-hidden className="size-4 text-amber-300" /> Knowledge health
      </h2>
      <p className="text-xs text-zinc-400">
        Where the graph&apos;s knowledge may be out of date: stale runbooks and docs, ownership handovers with no fresh runbook,
        and decisions that recent changes contradict. Answered from Cypher templates, cited and guarded like any question.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={onCheck} disabled={busy}>
          {busy ? <LoaderCircle aria-hidden className="motion-safe:animate-spin" /> : <HeartPulse aria-hidden />}
          Check knowledge health
        </Button>
        {last ? (
          <span className="text-[11px] text-zinc-400">
            last checked: run <span className="font-mono">{last.run_id}</span> · {last.citations.length} cited ids ·{" "}
            <a href="#brain-answer-h" className="text-sky-300 underline outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
              see the answer
            </a>
          </span>
        ) : null}
      </div>
    </section>
  );
}

function AnswerView({ a }: { a: BrainAnswer }) {
  const panel = useCypherPanel();
  const selected = useTenant();
  const openNode = (id: string) =>
    panel.open({
      template: "Q-CTX-1",
      title: `context of ${id}`,
      origin: `cited in brain answer ${a.run_id}`,
      ctx: { node: id, onset: nowMs() },
      tenant: a.tenant ?? selected,
    });
  const openStep = (s: BrainStep, i: number) => {
    const t2c = s.template === "T2C" || (a.tier === 3 && !!s.cypher && !s.template?.startsWith("Q-"));
    const tid = s.template ?? "T2C";
    panel.open({
      template: tid,
      title: `step ${i + 1} · ${s.tool}`,
      origin: `brain run ${a.run_id}${s.evidence_id ? ` → evidence ${s.evidence_id}` : ""}`,
      detail: `${s.via ?? ""}${s.via ? " · " : ""}tool args ${JSON.stringify(s.args)}${s.params ? "" : " (this backend did not record template params)"}${s.error ? ` · error: ${s.error}` : ""}`,
      recordedParams: s.params ?? null,
      recorded: { ms: s.ms, rows: s.rows },
      ctx: {
        node: typeof s.args.target_id === "string" ? s.args.target_id : typeof s.args.decision_id === "string" ? s.args.decision_id : undefined,
        onset: nowMs(),
      },
      tenant: a.tenant ?? selected,
      offline: t2c
        ? {
            reason: T2C_REASON,
            templates: { [tid]: { id: tid, purpose: "guarded text2cypher (tier 3)", cypher: s.cypher ?? "", file: "generated", limit: 0 } },
          }
        : null,
    });
  };

  return (
    <article className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <header className="space-y-2">
        <p className="text-xs text-zinc-400">
          Q: <span className="text-zinc-200">{a.question}</span>
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          {a.guard.ok ? (
            <StatusChip tone="pass" icon={ShieldCheck} title={`${a.guard.cited.length} cited ids, all seen by this run's queries`}>
              citation guard ✓
            </StatusChip>
          ) : (
            <StatusChip tone="fail" icon={ShieldX} title={a.guard.reason}>
              citation guard ✗
            </StatusChip>
          )}
          <StatusChip tone={a.tier === 3 ? "warn" : "info"} icon={a.tier === 3 ? Wand2 : undefined}>
            {TIER_TEXT[a.tier] ?? `tier ${a.tier}`}
          </StatusChip>
          {a.tier === 3 ? <StatusChip tone="warn">text2cypher</StatusChip> : null}
          <StatusChip tone="na">intent: {a.intent}</StatusChip>
          <span className="text-[11px] text-zinc-400">
            {a.answered_by} · {fmtMs(a.ms)} · <span className="font-mono">{a.run_id}</span>
          </span>
        </div>
        {!a.guard.ok ? (
          <p role="alert" className="text-xs text-red-200">
            Guard: {a.guard.reason || "failed"}
            {a.guard.unseen.length ? ` · unseen ids: ${a.guard.unseen.join(", ")}` : ""}
          </p>
        ) : null}
      </header>

      <Markdownish text={a.answer} onOpenNode={openNode} />

      <AnswerGraph key={`${a.tenant}:${a.run_id}`} answer={a} />

      {a.sources.length ? (
        <div>
          <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-400 uppercase">Sources</h3>
          <ul className="space-y-0.5 text-xs">
            {a.sources.map((u) => (
              <li key={u}>
                {safeHttpUrl(u) ? (
                  <a href={u} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 break-all text-sky-300 underline">
                    {u} <ExternalLink aria-hidden className="size-3" />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                ) : (
                  /* only http(s) URLs become links: a javascript:/data: source from the graph stays inert text */
                  <span className="break-all font-mono text-zinc-300">{u}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-zinc-400 uppercase">Via (graph steps, in order)</h3>
        {a.steps.length === 0 ? (
          <p className="text-xs text-zinc-300">No graph step was recorded for this answer.</p>
        ) : (
          <ol className="space-y-1" aria-label="Graph steps behind the answer">
            {a.steps.map((s, i) => (
              <Fragment key={`${i}:${s.tool}`}>
                {i > 0 ? (
                  <li aria-hidden className="pl-3 text-zinc-600">
                    <ArrowDown className="size-3" />
                  </li>
                ) : null}
                <li className={cn("rounded-md border px-2 py-1.5", s.error ? "border-red-500/50" : "border-zinc-700")}>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono text-zinc-400">{i + 1}.</span>
                    <span className="font-mono font-semibold text-zinc-100">{s.tool}</span>
                    <button
                      type="button"
                      onClick={() => openStep(s, i)}
                      className="inline-flex min-h-6 items-center rounded bg-violet-500/15 px-1 font-mono text-[11px] text-violet-200 outline-none hover:bg-violet-500/25 focus-visible:ring-2 focus-visible:ring-violet-300"
                      aria-label={`${s.template ?? "query"}: open the Cypher panel for step ${i + 1} (${s.tool})`}
                    >
                      {s.template ?? "query"}
                    </button>
                    {s.template === "T2C" ? <StatusChip tone="warn" icon={Wand2}>text2cypher</StatusChip> : null}
                    <span className="ml-auto font-mono text-[11px] text-zinc-400">
                      {s.rows ?? "–"} row{s.rows === 1 ? "" : "s"} · {fmtMs(s.ms)}
                    </span>
                  </div>
                  {s.via ? <p className="mt-0.5 font-mono text-[11px] break-words text-zinc-300">{s.via}</p> : null}
                  {s.error ? (
                    <p className="mt-0.5 flex items-center gap-1 text-[11px] text-red-300">
                      <CircleAlert aria-hidden className="size-3" /> {s.error}
                    </p>
                  ) : null}
                </li>
              </Fragment>
            ))}
          </ol>
        )}
      </div>
    </article>
  );
}

/** Minimal renderer for the brain's markdown: paragraphs, "- " bullets, **bold**, and [id] node chips. */
function Markdownish({ text, onOpenNode }: { text: string; onOpenNode: (id: string) => void }) {
  const blocks: { kind: "p" | "ul"; lines: string[] }[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) continue;
    const bullet = /^\s*[-*]\s+/.test(line);
    const last = blocks.at(-1);
    if (bullet) {
      const item = line.replace(/^\s*[-*]\s+/, "");
      if (last?.kind === "ul") last.lines.push(item);
      else blocks.push({ kind: "ul", lines: [item] });
    } else blocks.push({ kind: "p", lines: [line] });
  }
  return (
    <div className="space-y-2 text-sm leading-6 text-zinc-100">
      {blocks.map((b, i) =>
        b.kind === "ul" ? (
          <ul key={i} className="list-disc space-y-1 pl-5 marker:text-zinc-500">
            {b.lines.map((l, j) => (
              <li key={j}>
                <Inline text={l} onOpenNode={onOpenNode} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={i}>
            <Inline text={b.lines[0]} onOpenNode={onOpenNode} />
          </p>
        ),
      )}
    </div>
  );
}

function Inline({ text, onOpenNode }: { text: string; onOpenNode: (id: string) => void }) {
  const parts = text.split(/(\[[^\]\s]+\]|\*\*[^*]+\*\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        const id = p.match(/^\[([^\]\s]+)\]$/)?.[1];
        if (id) {
          return (
            <button
              key={i}
              type="button"
              onClick={() => onOpenNode(id)}
              className="mx-0.5 inline-flex items-center rounded border border-sky-500/50 bg-sky-500/10 px-1 align-baseline font-mono text-[12px] leading-5 text-sky-100 outline-none hover:bg-sky-500/20 focus-visible:ring-2 focus-visible:ring-sky-400"
              aria-label={`${id}: open its graph context in the Cypher panel`}
            >
              {id}
            </button>
          );
        }
        const bold = p.match(/^\*\*([^*]+)\*\*$/)?.[1];
        return bold ? <strong key={i}>{bold}</strong> : <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}
