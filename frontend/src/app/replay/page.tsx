import type { Metadata } from "next";
import { PageIntro } from "@/components/site/PageIntro";
import { ReplayIndex } from "@/components/replay/ReplayIndex";

export const metadata: Metadata = { title: "Replay · Faultline" };

export default function ReplayIndexPage() {
  return (
    <>
      <PageIntro eyebrow="Replay" title="Recorded runs," accent="played back" after=".">
        Each recorded incident replays from its exports, with the query behind every step; no backend needed.
      </PageIntro>
      <ReplayIndex />
    </>
  );
}
