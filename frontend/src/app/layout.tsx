import type { Metadata } from "next";
import { Geist_Mono, Instrument_Serif, Inter, Mona_Sans } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { BASE_PATH } from "@/lib/site";
import "./globals.css";

// body and headings: Inter (variable), set tight
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// the hero headline: Mona Sans (open, variable weight and width), set heavy, wide and tight
const mona = Mona_Sans({
  variable: "--font-mona",
  subsets: ["latin"],
  axes: ["wdth"],
});

// display serif with a true italic, for the hero headline only
const display = Instrument_Serif({
  variable: "--font-instrument",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "Faultline: no path, no claim",
  description:
    "On-call agent whose brain is a per-tenant FalkorDB operational context graph: what breaks, why (graph path plus evidence), and who fixes it.",
};

// the intro plays once per tab, only when the document itself loads on the home page
const INTRO_SCRIPT =
  `try{var p=location.pathname.slice(${JSON.stringify(BASE_PATH)}.length).replace(/\\/$/,'');` +
  "if(p!==''||sessionStorage.getItem('fl-intro')||matchMedia('(prefers-reduced-motion: reduce)').matches){window.__flIntroSkip=true;document.documentElement.dataset.flSeen='1'}}" +
  "catch(e){window.__flIntroSkip=true;document.documentElement.dataset.flSeen='1'}";

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`dark ${inter.variable} ${mona.variable} ${geistMono.variable} ${display.variable} h-full antialiased`}
    >
      <head>
        {/* before first paint: skip the home intro on a repeat visit in this tab or under reduced motion */}
        <script dangerouslySetInnerHTML={{ __html: INTRO_SCRIPT }} />
      </head>
      <body className="fl-body flex min-h-full flex-col text-zinc-100">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
