import type { MetadataRoute } from "next";
import { serverGet } from "@/lib/api-server";
import type { GameListOut, PlayerListItem, TournamentListItem } from "@/types/api";

// `||`, not `??`: the docker build passes this arg through as an empty string
// when it is unset, and "" would produce relative sitemap entries -- which are
// invalid, every <loc> must be absolute. Set NEXT_PUBLIC_SITE_URL at build
// time for production (see docker-compose.yml).
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/mafia`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/mafia/games`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/mafia/rating`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/mafia/tournaments`, changeFrequency: "weekly", priority: 0.8 },
  ];

  // Постранично, а не одним запросом с limit=100: игры после сотой просто не
  // индексировались. Верхние границы limit у обеих ручек -- 500.
  async function allGames(): Promise<GameListOut["items"]> {
    const pageSize = 500;
    const items: GameListOut["items"] = [];
    for (let offset = 0; ; offset += pageSize) {
      const page = await serverGet<GameListOut>("/api/games", { limit: pageSize, offset });
      items.push(...page.items);
      if (items.length >= page.total || page.items.length === 0) return items;
    }
  }

  async function allPlayers(): Promise<PlayerListItem[]> {
    const pageSize = 500;
    const items: PlayerListItem[] = [];
    for (let offset = 0; ; offset += pageSize) {
      const page = await serverGet<PlayerListItem[]>("/api/players", { limit: pageSize, offset });
      items.push(...page);
      if (page.length < pageSize) return items;
    }
  }

  try {
    const [players, gameItems, tournaments] = await Promise.all([
      allPlayers(),
      allGames(),
      serverGet<TournamentListItem[]>("/api/tournaments"),
    ]);

    const playerRoutes: MetadataRoute.Sitemap = players.map((p) => ({
      url: `${SITE_URL}/mafia/${p.slug}`,
      changeFrequency: "weekly",
      priority: 0.5,
    }));
    const gameRoutes: MetadataRoute.Sitemap = gameItems.map((g) => ({
      url: `${SITE_URL}/mafia/games/${g.id}`,
      changeFrequency: "monthly",
      priority: 0.3,
    }));

    const tournamentRoutes: MetadataRoute.Sitemap = tournaments.map((t) => ({
      url: `${SITE_URL}/mafia/tournaments/${t.slug}`,
      changeFrequency: "weekly",
      priority: 0.6,
    }));

    return [...staticRoutes, ...tournamentRoutes, ...playerRoutes, ...gameRoutes];
  } catch {
    return staticRoutes;
  }
}
