import { PageIntro } from "@/components/site/PageIntro";
import { BrainView } from "@/components/brain/BrainView";
import { LiveOnly } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

export default function BrainPage() {
  if (STATIC_SITE) {
    return (
      <LiveOnly
        feature="The company brain"
        what="It answers who owns, knows and decided what by running read-only Cypher against the tenant graph."
      />
    );
  }
  return (
    <>
      <PageIntro eyebrow="Company brain" title="Who owns, knows" accent="and decided" after=" what.">
        Answered by read-only Cypher on the tenant graph; every id an answer cites was returned by a query of that question.
      </PageIntro>
      <BrainView />
    </>
  );
}
