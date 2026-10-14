/** A titled card section in the incident room's right column (keyboard-reachable heading). */
export function Section({
  id,
  title,
  aside,
  children,
}: {
  id: string;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-h`} className="fl-card rounded-2xl p-4">
      <div className="mb-2 flex items-center gap-2">
        <h2 id={`${id}-h`} className="text-sm font-semibold text-zinc-50">
          {title}
        </h2>
        {aside ? <div className="ml-auto flex items-center gap-1.5">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}
