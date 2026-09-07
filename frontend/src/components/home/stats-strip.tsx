import { serverGet } from "@/lib/api-server";
import type { SiteStats } from "@/types/api";
import { Reveal } from "@/components/reveal";
import { Container } from "@/components/ui/container";
import { formatNumber, plural } from "@/lib/format";

// Раньше здесь тянулся весь список игроков клуба только ради len(), плюс
// отдельный запрос за играми. Теперь один эндпоинт с тремя COUNT'ами.
async function getStats() {
  return serverGet<SiteStats>("/api/stats");
}

export async function StatsStrip() {
  const { games_count, players_count, tournaments_count } = await getStats();

  const stats = [
    { value: games_count, label: `${plural(games_count, ["игра проведена", "игры проведено", "игр проведено"])}` },
    { value: tournaments_count, label: plural(tournaments_count, ["турнир", "турнира", "турниров"]) },
    { value: players_count, label: `${plural(players_count, ["игрок", "игрока", "игроков"])} в клубе` },
  ];

  return (
    <section className="border-y border-ink-800 bg-ink-900/60">
      <Container className="grid grid-cols-3 divide-x divide-ink-800 py-10">
        {stats.map((stat, i) => (
          <Reveal
            key={stat.label}
            delay={i * 0.08}
            className="px-2 text-center first:pl-0 last:pr-0 sm:px-6"
          >
            {/* Три колонки вместо двух -- на узких экранах числа немного
                сжаты по горизонтали, поэтому кегль числа стартует меньше и
                растёт только от sm:. */}
            <p className="font-mono text-3xl font-medium text-ink-50 sm:text-4xl md:text-5xl">
              {formatNumber(stat.value)}
            </p>
            <p className="mt-2 text-sm text-ink-400">{stat.label}</p>
          </Reveal>
        ))}
      </Container>
    </section>
  );
}
