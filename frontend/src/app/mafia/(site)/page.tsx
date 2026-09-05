import type { Metadata } from "next";
import { Hero } from "@/components/home/hero";
import { StatsStrip } from "@/components/home/stats-strip";
import { ExploreSection } from "@/components/home/explore-section";
import { RatingTeaser } from "@/components/home/rating-teaser";

export const metadata: Metadata = {
  title: "Главная",
};

// Always fresh: stats (games/players count) change whenever an admin adds a
// game. Explicit rather than relying on the no-store fetch alone -- see
// lib/api.ts for why a build-time prerender attempt would otherwise crash.
export const revalidate = 300;

export default function HomePage() {
  return (
    <>
      <Hero />
      <StatsStrip />
      <ExploreSection />
      <RatingTeaser />
    </>
  );
}
