import type { Metadata } from "next";
import { Big_Shoulders, Source_Sans_3 } from "next/font/google";
import Link from "next/link";
import { getHealth } from "@/lib/api";
import { REPO_URL } from "@/lib/site";
import "./globals.css";

// Scores and headings: a condensed stadium face. Everything else: a quiet, legible sans.
const scoreboard = Big_Shoulders({
  subsets: ["latin"],
  weight: ["600", "800"],
  variable: "--font-scoreboard",
});
const body = Source_Sans_3({ subsets: ["latin"], variable: "--font-body" });

export const metadata: Metadata = {
  title: "Fantasy GM",
  description: "Your fantasy football leagues: rosters, pickups, and analytics",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The backend may be down; pages render their own error panel, so no banner then.
  const demo = await getHealth().then(
    (h) => h.demo_mode,
    () => false,
  );
  return (
    <html lang="en" className={`h-full antialiased ${scoreboard.variable} ${body.variable}`}>
      <body className="flex min-h-full flex-col">
        {demo && (
          <div className="bg-accent text-accent-ink">
            <p className="mx-auto max-w-6xl px-4 py-1.5 text-xs">
              <strong>Demo league.</strong> Real NFL players and weekly points; the teams, managers and moves are made
              up. Read-only.{" "}
              <a href={REPO_URL} className="font-semibold underline underline-offset-2">
                View the code on GitHub
              </a>
            </p>
          </div>
        )}
        <header className="border-b border-line">
          <div className="mx-auto flex h-12 max-w-6xl items-center justify-between gap-4 px-4">
            <Link href="/" className="font-display text-xl font-extrabold tracking-wide text-ink">
              Fantasy GM
            </Link>
            <a href={REPO_URL} className="text-xs text-ink-2 hover:text-ink">
              GitHub
            </a>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
