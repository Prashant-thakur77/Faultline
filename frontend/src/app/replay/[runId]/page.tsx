import type { Metadata } from "next";
import { REPLAY_RUNS } from "@/lib/replay";
import { ReplayRoom } from "@/components/replay/ReplayRoom";

/** Recordings are static files, so their pages can be pre-rendered (GitHub Pages replay build). */
export function generateStaticParams() {
  return REPLAY_RUNS.map((runId) => ({ runId }));
}

export async function generateMetadata({ params }: { params: Promise<{ runId: string }> }): Promise<Metadata> {
  const { runId } = await params;
  return { title: `${decodeURIComponent(runId)} · Replay · Faultline` };
}

export default async function ReplayPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <ReplayRoom name={decodeURIComponent(runId)} />;
}
