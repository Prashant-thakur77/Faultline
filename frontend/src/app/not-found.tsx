import Link from "next/link";
import { CircleHelp } from "lucide-react";
import { LiveOnly } from "@/components/site/LiveOnly";
import { StatusChip } from "@/components/StatusChip";
import { STATIC_SITE } from "@/lib/site";

/**
 * 404. On the static replay site this is also what an incident room or preflight deep link
 * (/incidents/<id>, /preflight/<pr>) lands on, so it explains that those need the live backend.
 */
export default function NotFound() {
  if (STATIC_SITE) {
    return (
      <LiveOnly
        feature="This page"
        title="Not on the static replay site"
        chip="Not found"
        what="It does not exist on the static replay site. Incident rooms, preflight results and the brain are read from the live graph."
      />
    );
  }
  return (
    <div className="flex flex-1 items-start justify-center p-8">
      <section className="w-full max-w-xl space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-5">
        <StatusChip tone="na" icon={CircleHelp}>
          not found
        </StatusChip>
        <h1 className="text-lg font-semibold text-zinc-50">Page not found</h1>
        <p className="text-sm text-zinc-300">
          No page lives at this address.{" "}
          <Link href="/" className="text-sky-300 underline">
            Back to the incident room
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
