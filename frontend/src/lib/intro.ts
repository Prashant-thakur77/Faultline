import { useSyncExternalStore } from "react";

/** Has the home intro finished (wiped, or skipped)? The hero starts its reveal on this. One per document. */
let done = false;
const subs = new Set<() => void>();

export const introStore = {
  done(): void {
    if (done) return;
    done = true;
    subs.forEach((f) => f());
  },
  subscribe(f: () => void): () => void {
    subs.add(f);
    return () => subs.delete(f);
  },
  get: (): boolean => done,
};

export function useIntroDone(): boolean {
  return useSyncExternalStore(introStore.subscribe, introStore.get, () => false);
}
