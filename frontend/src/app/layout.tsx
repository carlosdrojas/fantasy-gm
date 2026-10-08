import type { Metadata } from "next";
import { Big_Shoulders, Source_Sans_3 } from "next/font/google";
import Link from "next/link";
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

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`h-full antialiased ${scoreboard.variable} ${body.variable}`}>
      <body className="flex min-h-full flex-col">
        <header className="border-b border-line">
          <div className="mx-auto flex h-12 max-w-6xl items-center px-4">
            <Link href="/" className="font-display text-xl font-extrabold tracking-wide text-ink">
              Fantasy GM
            </Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
