import type { Metadata } from "next";
import { PhonePage } from "@/components/oncall/PhonePage";
import { LiveOnly } from "@/components/site/LiveOnly";
import { STATIC_SITE } from "@/lib/site";

export const metadata: Metadata = { title: "Page · On call · Faultline" };

/**
 * Static replay site: one placeholder path so the export has something to render (a dynamic route needs at least
 * one param under output: "export"); every other page id gets the site's 404 page. The live build exports no
 * generateStaticParams (undefined), so the route stays dynamic.
 */
export const generateStaticParams = STATIC_SITE ? () => [{ id: "live-only" }] : undefined;

/**
 * /oncall/page/<id>?t=<token>: the link a page carries (in-app, Slack, Telegram, email). `t` is the page's signed ack
 * token; it is only passed on to POST /api/pages/{id}/ack and never shown or stored.
 */
export default async function OnCallPagePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (STATIC_SITE) {
    return (
      <LiveOnly
        feature="A page"
        title="Pages are live server only"
        chip="Live server only"
        what="A page is the link the on-call person receives: the verdict, the proof path, who fixes it and a signed Ack, read from the tenant's FalkorDB graph."
      />
    );
  }
  const { id } = await params;
  const sp = await searchParams;
  const t = typeof sp.t === "string" && /^[A-Za-z0-9._~:+/=-]{8,2048}$/.test(sp.t) ? sp.t : null;
  return <PhonePage pageId={decodeURIComponent(id)} token={t} />;
}
