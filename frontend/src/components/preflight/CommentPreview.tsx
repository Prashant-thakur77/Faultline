"use client";

import { Fragment } from "react";
import { ExternalLink } from "lucide-react";

/**
 * Preview of the PR comment the preflight would post (markdown from the API). A deliberately
 * small renderer: headings, bullets, paragraphs, **bold**, [text](url) and <sub>…</sub>.
 * No HTML is injected; only http(s) links are clickable, anything else is shown as a path.
 */
export function CommentPreview({ markdown }: { markdown: string }) {
  const blocks: { kind: "h" | "p" | "ul" | "sub"; lines: string[]; level?: number }[] = [];
  for (const raw of markdown.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      blocks.push({ kind: "p", lines: [] });
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      blocks.push({ kind: "h", lines: [h[2]], level: h[1].length });
      continue;
    }
    const sub = line.match(/^<sub>(.*)<\/sub>$/);
    if (sub) {
      blocks.push({ kind: "sub", lines: [sub[1]] });
      continue;
    }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    const last = blocks.at(-1);
    if (li) {
      if (last?.kind === "ul") last.lines.push(li[1]);
      else blocks.push({ kind: "ul", lines: [li[1]] });
    } else if (last?.kind === "p" && last.lines.length) last.lines.push(line);
    else blocks.push({ kind: "p", lines: [line] });
  }
  return (
    <div className="space-y-2 text-sm leading-6 text-zinc-100">
      {blocks
        .filter((b) => b.lines.length)
        .map((b, i) =>
          b.kind === "h" ? (
            <p key={i} className={b.level && b.level <= 3 ? "text-base font-semibold text-zinc-50" : "font-semibold"}>
              <Inline text={b.lines[0]} />
            </p>
          ) : b.kind === "ul" ? (
            <ul key={i} className="list-disc space-y-1 pl-5 marker:text-zinc-500">
              {b.lines.map((l, j) => (
                <li key={j}>
                  <Inline text={l} />
                </li>
              ))}
            </ul>
          ) : b.kind === "sub" ? (
            <p key={i} className="text-xs text-zinc-400">
              <Inline text={b.lines[0]} />
            </p>
          ) : (
            <p key={i}>
              <Inline text={b.lines.join(" ")} />
            </p>
          ),
        )}
    </div>
  );
}

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        const bold = p.match(/^\*\*([^*]+)\*\*$/)?.[1];
        if (bold) return <strong key={i}>{bold}</strong>;
        const link = p.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
        if (link) {
          const [, label, href] = link;
          return /^https?:\/\//.test(href) ? (
            <a key={i} href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-sky-300 underline">
              {label}
              <ExternalLink aria-hidden className="size-3" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            <span key={i} className="text-sky-200" title={`not a web link: ${href}`}>
              {label} <span className="font-mono text-xs text-zinc-400">({href})</span>
            </span>
          );
        }
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}
