import { Unplug } from "lucide-react";
import { StatusChip } from "@/components/StatusChip";

/**
 * The static replay site (GitHub Pages) in place of "What Faultline has learned": learned state lives in the tenant's
 * on-call graph in FalkorDB and changes as people use Faultline, so a file export would be a stale sample. Says so,
 * shows nothing in its place.
 */
export function LearnedLiveOnly() {
  return (
    <section id="learned" aria-labelledby="learned-h" className="fl-card mx-auto w-full max-w-2xl space-y-2 rounded-2xl px-5 py-4">
      <StatusChip tone="warn" icon={Unplug}>
        Live server only
      </StatusChip>
      <h2 id="learned-h" className="text-[15px] font-[560] tracking-[-0.01em] text-zinc-50">
        What Faultline has learned
      </h2>
      <p className="text-sm leading-relaxed text-zinc-300">
        Preferences, guidelines, learned responders, knowledge gaps, standing approvals to consider and forget receipts are
        read from the tenant&apos;s on-call graph in FalkorDB and change as people approve, reject, ack and ask. This static
        replay site has no API and no FalkorDB behind it, so it shows none of them rather than a sample.
      </p>
    </section>
  );
}
