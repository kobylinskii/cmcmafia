import type { MetadataRoute } from "next";
import { serverGet } from "@/lib/api";
import type { GameListOut, PlayerListItem } from "@/types/api";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/mafia`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/mafia/games`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/mafia/rating`, changeFrequency: "daily", priority: 0.8 },
  ];

  try {
    const [players, games] = await Promise.all([
      serverGet<PlayerListItem[]>("/api/players"),
      serverGet<GameListOut>("/api/games", { limit: 100 }),
    ]);

    const playerRoutes: MetadataRoute.Sitemap = players.map((p) => ({
      url: `${SITE_URL}/mafia/${p.slug}`,
      changeFrequency: "weekly",
      priority: 0.5,
    }));
    const gameRoutes: MetadataRoute.Sitemap = games.items.map((g) => ({
      url: `${SITE_URL}/mafia/games/${g.id}`,
      changeFrequency: "monthly",
      priority: 0.3,
    }));

    return [...staticRoutes, ...playerRoutes, ...gameRoutes];
  } catch {
    return staticRoutes;
  }
}
