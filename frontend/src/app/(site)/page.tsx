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
// Рендер на каждый запрос, а не пререндер при сборке. Кеширование живёт
// уровнем ниже -- в serverGet, где у каждого запроса к API стоит
// next: { revalidate, tags } (см. lib/api-server.ts), и сбрасывается по тегу
// после правки в админке. Страничного revalidate здесь быть не должно: Next
// тогда пытается собрать страницу статически в момент `docker compose build`,
// где бэкенда ещё нет, и сборка падает на getaddrinfo ENOTFOUND api.
export const dynamic = "force-dynamic";

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
