import { BASE_PATH } from "@/lib/site";

/**
 * A faint topographic map with a fault through it (our own art: scripts/gen-contours.mjs draws contours.svg, and
 * scripts/raster_contours.py renders it once to contours.webp), drifting slowly behind a section and fading out at its
 * edges. Decorative. A bitmap, not the SVG: the SVG is one path of thousands of segments, and drawn live over a large
 * layer it was re-rasterised as it moved, 100-300 ms scroll stalls on an integrated GPU.
 * Rendered as an element, not a CSS url(), so the Pages base path applies.
 */
export function Contours({ className = "", opacity = 0.1 }: { className?: string; opacity?: number }) {
  return (
    <div aria-hidden className={"pointer-events-none absolute inset-0 -z-10 overflow-hidden [mask-image:radial-gradient(ellipse_75%_70%_at_50%_45%,#000_35%,transparent_100%)] " + className}>
      <div className="fl-contours absolute -inset-[6%] bg-cover bg-center"
           style={{ backgroundImage: `url(${BASE_PATH}/brand/contours.webp)`, opacity }} />
    </div>
  );
}
