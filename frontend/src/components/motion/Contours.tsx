import { BASE_PATH } from "@/lib/site";

/**
 * A faint topographic map with a fault through it (public/brand/contours.svg, our own art from
 * scripts/gen-contours.mjs), drifting slowly behind a section and fading out at its edges. Decorative.
 * Rendered as an element, not a CSS url(), so the Pages base path applies.
 */
export function Contours({ className = "", opacity = 0.1 }: { className?: string; opacity?: number }) {
  return (
    <div aria-hidden className={"pointer-events-none absolute inset-0 -z-10 overflow-hidden [mask-image:radial-gradient(ellipse_75%_70%_at_50%_45%,#000_35%,transparent_100%)] " + className}>
      <div className="fl-contours absolute -inset-[6%] bg-cover bg-center"
           style={{ backgroundImage: `url(${BASE_PATH}/brand/contours.svg)`, opacity }} />
    </div>
  );
}
