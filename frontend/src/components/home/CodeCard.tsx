"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";

const KW = /\b(OPTIONAL MATCH|MATCH|CALL|YIELD|RETURN|WITH|WHERE|ORDER BY|LIMIT|UNWIND|AS|IN)\b|(algo\.\w+)|(\$\w+)|('[^']*')/g;

/** Minimal Cypher colouring: keywords, the algo.* procedure, $params and string literals. */
function highlight(line: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  for (const m of line.matchAll(KW)) {
    if (m.index > last) out.push(line.slice(last, m.index));
    const cls = m[1] ? "text-sky-300" : m[2] ? "text-[var(--fl-ember)]" : m[3] ? "text-[var(--fl-iris)]" : "text-emerald-300/90";
    out.push(<span key={m.index} className={cls}>{m[0]}</span>);
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

/** JSON: keys in grey-blue, string values in green. */
function jsonLine(line: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  for (const m of line.matchAll(/("[^"]*")(\s*:)?/g)) {
    if (m.index > last) out.push(line.slice(last, m.index));
    out.push(<span key={m.index} className={m[2] ? "text-sky-300" : "text-emerald-300/90"}>{m[1]}</span>);
    if (m[2]) out.push(m[2]);
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

/** A code card with a copy button (the copied text is exactly what is shown). */
export function CodeCard({ title, meta, code, lang = "cypher", bare = false }: { title: string; meta?: string; code: string; lang?: "cypher" | "shell" | "json"; bare?: boolean }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      setCopied(false);   // no clipboard permission: the text is still selectable
    }
  };
  return (
    <figure className={"min-w-0 overflow-hidden " + (bare ? "" : "rounded-2xl border border-white/10 bg-[#0c0d0e]")}>
      <figcaption className="flex items-center gap-3 border-b border-white/[0.07] px-4 py-2.5">
        <span className="shrink-0 whitespace-nowrap font-mono text-[11px] uppercase tracking-[0.18em] text-zinc-300">{title}</span>
        {meta ? <span className="truncate font-mono text-[11px] text-zinc-400">{meta}</span> : null}
        <button type="button" onClick={copy} aria-label={copied ? "Copied" : `Copy ${title}`}
                className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-zinc-300 outline-none transition-colors duration-150 hover:bg-white/[0.06] focus-visible:ring-2 focus-visible:ring-sky-400">
          {copied ? <Check className="size-3.5 text-emerald-300" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
          <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
        </button>
      </figcaption>
      {/* focusable: a long line scrolls sideways, and keyboard users must be able to scroll it too */}
      <pre tabIndex={0} aria-label={`${title} code`} className="overflow-x-auto px-4 py-3.5 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400 font-mono text-[12.5px] leading-relaxed text-zinc-200"><code>
        {code.split("\n").map((l, i) => (
          <span key={i} className="block whitespace-pre-wrap break-all">
            {lang === "shell" ? <>{/^\s/.test(l) ? null : <span className="select-none text-zinc-500">$ </span>}{l}</>
              : lang === "json" ? jsonLine(l) : highlight(l)}
          </span>
        ))}
      </code></pre>
    </figure>
  );
}
