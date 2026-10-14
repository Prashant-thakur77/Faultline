/**
 * Client-side unified line diff of the exact action's `before` → `after` file contents
 * (display only: the server decides what changes; this renders what it returned).
 * LCS over lines; hunks carry 3 lines of context like `diff -u`.
 */

export type DiffLine = { kind: "ctx" | "add" | "del"; text: string; oldNo: number | null; newNo: number | null };
export interface Hunk {
  header: string;
  lines: DiffLine[];
}

const MAX_LINES = 4000;

function splitLines(s: string): string[] {
  const lines = s.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

export function lineDiff(before: string, after: string): DiffLine[] | null {
  const a = splitLines(before);
  const b = splitLines(after);
  if (a.length > MAX_LINES || b.length > MAX_LINES) return null;
  // Trim the common prefix/suffix first so the DP table stays small for one-line edits.
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let suf = 0;
  while (suf < a.length - pre && suf < b.length - pre && a[a.length - 1 - suf] === b[b.length - 1 - suf]) suf++;
  const A = a.slice(pre, a.length - suf);
  const B = b.slice(pre, b.length - suf);
  const n = A.length;
  const m = B.length;
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let oldNo = 1;
  let newNo = 1;
  for (let k = 0; k < pre; k++) out.push({ kind: "ctx", text: a[k], oldNo: oldNo++, newNo: newNo++ });
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && A[i] === B[j]) {
      out.push({ kind: "ctx", text: A[i], oldNo: oldNo++, newNo: newNo++ });
      i++;
      j++;
    } else if (i < n && (j >= m || dp[i + 1][j] >= dp[i][j + 1])) {
      // Removals before additions, like diff -u.
      out.push({ kind: "del", text: A[i], oldNo: oldNo++, newNo: null });
      i++;
    } else {
      out.push({ kind: "add", text: B[j], oldNo: null, newNo: newNo++ });
      j++;
    }
  }
  for (let k = a.length - suf; k < a.length; k++) out.push({ kind: "ctx", text: a[k], oldNo: oldNo++, newNo: newNo++ });
  return out;
}

export function toHunks(lines: DiffLine[], context = 3): Hunk[] {
  const changed = lines.map((l, i) => (l.kind === "ctx" ? -1 : i)).filter((i) => i >= 0);
  if (!changed.length) return [];
  const ranges: [number, number][] = [];
  for (const i of changed) {
    const lo = Math.max(0, i - context);
    const hi = Math.min(lines.length - 1, i + context);
    const last = ranges[ranges.length - 1];
    if (last && lo <= last[1] + 1) last[1] = Math.max(last[1], hi);
    else ranges.push([lo, hi]);
  }
  return ranges.map(([lo, hi]) => {
    const slice = lines.slice(lo, hi + 1);
    const oldStart = slice.find((l) => l.oldNo !== null)?.oldNo ?? 0;
    const newStart = slice.find((l) => l.newNo !== null)?.newNo ?? 0;
    const oldLen = slice.filter((l) => l.kind !== "add").length;
    const newLen = slice.filter((l) => l.kind !== "del").length;
    return { header: `@@ -${oldStart},${oldLen} +${newStart},${newLen} @@`, lines: slice };
  });
}
