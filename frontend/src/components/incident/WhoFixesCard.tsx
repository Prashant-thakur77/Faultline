"use client";

import { useState } from "react";
import { Network, TriangleAlert, UserRound, Users } from "lucide-react";
import { fmtValue } from "@/lib/format";
import type { PlanItem, PlanResponse, WhoFixesRow } from "@/lib/types";
import { StatusChip } from "@/components/StatusChip";
import { ViaFalkor } from "@/components/cypher/ViaFalkor";
import { Disclosure, useFold } from "@/components/ui/Disclosure";
import { PlanPending, TemplateButton } from "./ContainmentCard";
import { Section } from "./Section";

/**
 * Who fixes it: people ranked by the graph (Q-ORG-HARM, algo.HarmonicCentrality + commits,
 * resolutions and on-call), each with the reasons the query returned; the bus factor of the
 * changed service (Q-ORG-2); and the escalation tree (Q-ORG-MSF, algo.MSF).
 */
export function WhoFixesCard({
  plan,
  error,
  stage,
  onOpenPlanItem,
}: {
  plan: PlanResponse | null;
  error: string | null;
  stage: string;
  onOpenPlanItem: (item: PlanItem<unknown>, title: string) => void;
}) {
  const who = plan?.who_fixes ?? null;
  const bus = plan?.bus_factor ?? null;
  const tree = plan?.escalation_tree ?? null;
  const people = who?.payload?.rows ?? [];
  const names = new Map(people.map((p) => [p.person, p.name]));
  const bf = bus?.payload?.bus_factor ?? null;
  const inactive = bus?.payload?.top_contributor_inactive === true;
  const risky = (bf !== null && bf <= 1) || inactive;
  const target = typeof bus?.params?.target === "string" ? (bus.params.target as string) : null;

  return (
    <Section
      id="whofixes"
      title="Who fixes it"
      via={who ? <ViaFalkor template={who.template} label="the ranking" onOpen={() => onOpenPlanItem(who, "who fixes it")} /> : null}
    >
      {!who ? (
        <PlanPending error={error} stage={stage} what="routing" />
      ) : (
        <div className="space-y-4">
          {people.length === 0 ? (
            <p className="text-sm text-zinc-300">The ranking query returned no people for this cause.</p>
          ) : (
            <People people={people} />
          )}

          {bus && risky ? (
            <div role="note" className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-2.5 text-xs text-amber-100">
              <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-300" />
              <p>
                <strong className="font-semibold">Bus-factor warning:</strong>{" "}
                {bf !== null && bf <= 1 ? (
                  <>
                    bus factor {bf}
                    {target ? (
                      <>
                        {" "}
                        on <span className="font-mono">{target}</span>
                      </>
                    ) : null}
                    : one person holds most of the knowledge.
                  </>
                ) : null}
                {inactive ? " The top contributor is inactive." : null}
              </p>
            </div>
          ) : null}

          <Disclosure
            summary={
              <>
                Bus factor and escalation
                <span className="text-[var(--fl-subtle)]">
                  {bf !== null ? ` · bus factor ${bf}` : ""}
                  {tree ? ` · ${(tree.payload?.rows ?? []).length} escalation links` : ""}
                </span>
              </>
            }
          >
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <h3 className="text-xs font-medium text-zinc-400">Bus factor</h3>
                  {bus ? (
                    <span className="ml-auto">
                      <TemplateButton template={bus.template} label="the bus factor" onOpen={() => onOpenPlanItem(bus, "bus factor")} />
                    </span>
                  ) : null}
                </div>
                {!bus ? (
                  <PlanPending error={error} stage={stage} what="bus factor" />
                ) : (
                  <p className="flex flex-wrap items-center gap-2 text-xs text-zinc-300">
                    <StatusChip tone={risky ? "warn" : "pass"}>bus factor {bf ?? "\u2013"}</StatusChip>
                    {target ? (
                      <span>
                        on <span className="font-mono">{target}</span>
                      </span>
                    ) : null}
                    <span className="text-[var(--fl-subtle)]">{inactive ? "top contributor inactive" : "top contributor active"}</span>
                    {typeof bus.payload?.total_commits === "number" ? (
                      <span className="text-[var(--fl-subtle)]">· {bus.payload.total_commits} commits counted</span>
                    ) : null}
                  </p>
                )}
              </div>

              <div>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <h3 className="flex items-center gap-1 text-xs font-medium text-zinc-400">
                    <Network aria-hidden className="size-3.5" /> Escalation tree
                  </h3>
                  {tree ? (
                    <span className="ml-auto">
                      <TemplateButton template={tree.template} label="the escalation tree" onOpen={() => onOpenPlanItem(tree, "escalation tree")} />
                    </span>
                  ) : null}
                </div>
                {!tree ? (
                  <PlanPending error={error} stage={stage} what="escalation tree" />
                ) : (tree.payload?.rows ?? []).length === 0 ? (
                  <p className="text-xs text-zinc-300">No escalation edges returned.</p>
                ) : (
                  <ol className="list-decimal space-y-0.5 pl-5 font-mono text-xs text-zinc-300 marker:text-zinc-600" aria-label="Escalation tree edges (minimum spanning forest)">
                    {tree.payload!.rows.map((e) => (
                      <li key={`${e.from}-${e.to}`}>
                        <span title={names.get(e.from) ?? undefined}>{e.from}</span> <span aria-label="linked with">↔</span>{" "}
                        <span title={names.get(e.to) ?? undefined}>{e.to}</span>{" "}
                        <span className="text-[var(--fl-subtle)]">(w {Number.isInteger(e.w) ? e.w.toFixed(1) : fmtValue(e.w)})</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          </Disclosure>
        </div>
      )}
    </Section>
  );
}


/** The top pick in full; the rest one click away (still in the list, so the ranking stays one list). */
function People({ people }: { people: WhoFixesRow[] }) {
  const fold = useFold();
  const [all, setAll] = useState(!fold);
  const more = people.length - 1;
  return (
    <div>
      <ol className="space-y-1" aria-label="People ranked by the graph">
        {people.map((p, i) => (
          <li
            key={p.person}
            data-person={p.person}
            hidden={i > 0 && !all}
            className={"rounded-lg px-3 py-2.5 " + (i === 0 ? "bg-white/[0.04] ring-1 ring-white/[0.08]" : "")}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-[var(--fl-subtle)]">#{i + 1}</span>
              <UserRound aria-hidden className="size-3.5 text-zinc-400" />
              <span className={i === 0 ? "text-[15px] font-[560] text-zinc-50" : "text-sm font-medium text-zinc-100"}>{p.name ?? p.person}</span>
              <span className="font-mono text-[11px] text-[var(--fl-subtle)]">{p.person}</span>
              {i === 0 ? <StatusChip tone="info">top pick</StatusChip> : null}
              <span className="ml-auto font-mono text-[11px] text-[var(--fl-subtle)]" title="score from the ranking query">
                score {fmtValue(p.score)}
              </span>
            </div>
            {p.teams.length ? (
              <p className="mt-0.5 flex items-center gap-1 pl-5 text-[11px] text-[var(--fl-subtle)]">
                <Users aria-hidden className="size-3" /> {p.teams.join(", ")}
              </p>
            ) : null}
            {p.reasons.length ? (
              <ul className="mt-1 space-y-0.5 pl-5 text-xs text-zinc-300">
                {p.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
      {more > 0 ? (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll((a) => !a)}
          className="mt-1.5 inline-flex min-h-7 items-center rounded-md px-1 text-[13px] text-zinc-400 outline-none hover:text-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-400"
        >
          {all ? "Show only the top pick" : `Show ${more} more ${more === 1 ? "person" : "people"}`}
        </button>
      ) : null}
    </div>
  );
}
