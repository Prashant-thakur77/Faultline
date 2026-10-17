import { OnCallView } from "@/components/oncall/OnCallView";
import { LiveOnly } from "@/components/site/LiveOnly";
import { PageIntro } from "@/components/site/PageIntro";
import { STATIC_SITE } from "@/lib/site";

const ONCALL_WHAT =
  "On-call pages the person on call for the owning team, escalates when nobody acks, and handles a repeat under a standing contract; every page, ack and contract is a node in the tenant's FalkorDB graph.";

/** /oncall: who is on call, the live pager, contracts, the shift report and hand-offs (M19). */
export default function OnCallPage() {
  if (STATIC_SITE) {
    return <LiveOnly feature="On-call" title="On-call is live server only" chip="Live server only" what={ONCALL_WHAT} />;
  }
  return (
    <>
      <PageIntro eyebrow="On-call" title="Wake the right person," accent="only when it matters" after=".">
        Pages go to whoever the graph says is on call for the owning team, escalate along the tree when nobody acks, and
        stop for a repeat a human already approved under a contract.
      </PageIntro>
      <OnCallView />
    </>
  );
}
