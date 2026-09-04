import { serverGet } from "@/lib/api";
import type { GameListOut, PlayerListItem } from "@/types/api";
import { Reveal } from "@/components/reveal";
import { Container } from "@/components/ui/container";
import { formatNumber } from "@/lib/format";

async function getStats() {
  const [games, players] = await Promise.all([
    serverGet<GameListOut>("/api/games", { limit: 1 }),
    serverGet<PlayerListItem[]>("/api/players"),
  ]);
  return { gamesCount: games.total, playersCount: players.length };
}

export async function StatsStrip() {
  const { gamesCount, playersCount } = await getStats();

  const stats = [
    { value: gamesCount, label: "игр в архиве" },
    { value: playersCount, label: "игроков в клубе" },
  ];

  return (
    <section className="border-y border-ink-800 bg-ink-900/60">
      <Container className="grid grid-cols-2 divide-x divide-ink-800 py-10">
        {stats.map((stat, i) => (
          <Reveal key={stat.label} delay={i * 0.08} className="px-6 text-center first:pl-0 last:pr-0">
            <p className="font-mono text-4xl font-medium text-ink-50 md:text-5xl">
              {formatNumber(stat.value)}
            </p>
            <p className="mt-2 text-sm text-ink-400">{stat.label}</p>
          </Reveal>
        ))}
      </Container>
    </section>
  );
}
