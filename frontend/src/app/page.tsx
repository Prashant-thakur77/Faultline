import { ScenarioLauncher } from "@/components/ScenarioLauncher";
import { RecentIncidents } from "@/components/RecentIncidents";
import { StaticLanding } from "@/components/site/StaticLanding";
import { Hero } from "@/components/home/Hero";
import { ApiTabs } from "@/components/home/ApiTabs";
import { Features } from "@/components/home/Features";
import { Marquee } from "@/components/home/Marquee";
import { ProofStory } from "@/components/home/ProofStory";
import { SiteFooter } from "@/components/home/SiteFooter";
import { STATIC_SITE } from "@/lib/site";
import { SystemMap } from "@/components/home/SystemMap";
import { ProductTour } from "@/components/home/ProductTour";
import { Faq } from "@/components/home/Faq";
import { SectionRule } from "@/components/home/SectionRule";

export default function Home() {
  // GitHub Pages build: a landing page for the recorded replays (there is no API to launch runs).
  if (STATIC_SITE) return <StaticLanding />;
  return (
    <div className="w-full">
      <Hero />
      <Marquee />
      <Features />
      <SectionRule />
      <SystemMap />
      <SectionRule />
      <ProofStory />
      <SectionRule />
      <ProductTour />
      <SectionRule />
      <ApiTabs />
      <section id="run" aria-labelledby="run-title" className="scroll-mt-20 border-t border-white/[0.06]">
        <div className="mx-auto max-w-[1200px] px-5 py-24 sm:px-8">
          <h2 id="run-title" className="max-w-[920px] text-[clamp(1.9rem,4.2vw,3rem)] font-[510] leading-[1.08] tracking-[-0.022em] text-zinc-50">
            Watch the gate work.{" "}
            <span className="text-[var(--fl-muted)]">Every run happens on a fresh GRAPH.COPY clean room of the tenant graph. Pick a scenario, or open a recorded incident.</span>
          </h2>
          {/* on desktop both panels share one height and scroll inside themselves, never stretching the page */}
          <div className="mt-10 grid gap-6 lg:h-[min(78vh,720px)] lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <ScenarioLauncher />
            <RecentIncidents />
          </div>
        </div>
      </section>
      <SectionRule />
      <Faq />
      <SiteFooter />
    </div>
  );
}
