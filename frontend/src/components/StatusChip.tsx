import {
  CircleCheck,
  CircleHelp,
  CircleMinus,
  CircleX,
  Info,
  LoaderCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { Tone } from "@/lib/gate";
import { cn } from "@/lib/utils";

/**
 * Status is never colour-only: every chip carries an icon and a text label.
 * Colours are chosen for WCAG AA on the zinc-950/900 surfaces (300-level text on a
 * 10–15% tinted background).
 */

export const TONE_CLASS: Record<Tone, string> = {
  pass: "text-emerald-300 bg-emerald-500/10 border-emerald-500/40",
  fail: "text-red-300 bg-red-500/10 border-red-500/45",
  warn: "text-amber-300 bg-amber-500/10 border-amber-500/40",
  na: "text-zinc-300 bg-zinc-500/10 border-zinc-500/40",
  info: "text-sky-300 bg-sky-500/10 border-sky-500/40",
  running: "text-sky-300 bg-sky-500/10 border-sky-500/40",
};

export const TONE_ICON: Record<Tone, LucideIcon> = {
  pass: CircleCheck,
  fail: CircleX,
  warn: TriangleAlert,
  na: CircleMinus,
  info: Info,
  running: LoaderCircle,
};

export function StatusChip({
  tone,
  children,
  icon,
  className,
  title,
}: {
  tone: Tone;
  children: React.ReactNode;
  icon?: LucideIcon;
  className?: string;
  title?: string;
}) {
  const Icon = icon ?? TONE_ICON[tone] ?? CircleHelp;
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap",
        TONE_CLASS[tone],
        className,
      )}
    >
      <Icon
        aria-hidden
        className={cn("size-3.5 shrink-0", tone === "running" && "motion-safe:animate-spin")}
      />
      {children}
    </span>
  );
}
