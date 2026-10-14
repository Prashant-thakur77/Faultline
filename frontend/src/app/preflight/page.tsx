import { PageIntro } from "@/components/site/PageIntro";
import { PreflightView } from "@/components/preflight/PreflightView";
import { LiveOnly, PREFLIGHT_WHAT } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

/** /preflight[?pr=<pr id>&focus=<node>]: with ?pr= the latest recorded preflight for that PR is loaded. */
export default async function PreflightPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (STATIC_SITE) return <LiveOnly feature="Preflight" what={PREFLIGHT_WHAT} />;
  const sp = await searchParams;
  const focus = typeof sp.focus === "string" && sp.focus ? sp.focus : null;
  const pr = typeof sp.pr === "string" && sp.pr ? sp.pr : null;
  return (
    <>
      <PageIntro eyebrow="Preflight" title="Catch the risky change" accent="before" after=" it ships.">
        A pull request scored against the graph: what it can break, who should review it, and which active decisions it contradicts.
      </PageIntro>
      <PreflightView key={pr ?? ""} focus={focus} prRef={pr} />
    </>
  );
}
