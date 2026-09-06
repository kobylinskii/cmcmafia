import type { Metadata } from "next";
import Link from "next/link";
import { serverGet } from "@/lib/api-server";
import type { GameListOut, TournamentListItem } from "@/types/api";
import { Container } from "@/components/ui/container";
import { GamesFilterBar } from "@/components/games/filter-bar";
import { GameCard } from "@/components/games/game-card";
import { firstParam, intParam } from "@/lib/search-params";

export const metadata: Metadata = { title: "Игры" };
// Рендер на каждый запрос, а не пререндер при сборке. Кеширование живёт
// уровнем ниже -- в serverGet, где у каждого запроса к API стоит
// next: { revalidate, tags } (см. lib/api-server.ts), и сбрасывается по тегу
// после правки в админке. Страничного revalidate здесь быть не должно: Next
// тогда пытается собрать страницу статически в момент `docker compose build`,
// где бэкенда ещё нет, и сборка падает на getaddrinfo ENOTFOUND api.
export const dynamic = "force-dynamic";

export default async function GamesPage({
  searchParams,
}: PageProps<"/mafia/games">) {
  const params = await searchParams;
  // Через intParam, а не Number(): "abc" давало NaN, "0" и "-5" уходили в API
  // как есть, бэкенд отвечал 422 -- и страница падала в 500.
  const limit = intParam(params, "limit", { def: 10, min: 1, max: 100 });
  const offset = intParam(params, "offset", { def: 0, min: 0, max: 100_000 });
  const game_type = firstParam(params, "game_type");
  const tournament_slug = firstParam(params, "tournament_slug");
  const date_from = firstParam(params, "date_from");
  const date_to = firstParam(params, "date_to");

  const [data, tournaments] = await Promise.all([
    serverGet<GameListOut>("/api/games", {
      limit,
      offset,
      game_type,
      tournament_slug,
      date_from,
      date_to,
    }),
    serverGet<TournamentListItem[]>("/api/tournaments"),
  ]);

  const buildUrl = (nextOffset: number) => {
    const p = new URLSearchParams();
    if (game_type) p.set("game_type", game_type);
    if (tournament_slug) p.set("tournament_slug", tournament_slug);
    if (date_from) p.set("date_from", date_from);
    if (date_to) p.set("date_to", date_to);
    p.set("limit", String(limit));
    p.set("offset", String(nextOffset));
    return `/mafia/games?${p.toString()}`;
  };

  return (
    <Container className="py-14">
      <div className="max-w-2xl">
        <h1 className="font-display text-3xl font-medium text-ink-50 md:text-4xl">Игры клуба</h1>
        <p className="mt-3 text-ink-300">
          Все оценённые партии: состав, роли, баллы и итог каждой игры.
        </p>
      </div>

      <div className="mt-8">
        <GamesFilterBar tournaments={tournaments} />
      </div>

      <div className="mt-6 flex flex-col gap-3">
        {data.items.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-8 text-center text-ink-400">
            По этому фильтру пока нет сыгранных игр.
          </p>
        )}
        {data.items.map((game) => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>

      {data.total > limit && (
        <div className="mt-8 flex items-center justify-between text-sm text-ink-300">
          <Link
            href={buildUrl(Math.max(0, offset - limit))}
            aria-disabled={offset === 0}
            className={offset === 0 ? "pointer-events-none opacity-30" : "hover:text-ink-50"}
          >
            ← Новее
          </Link>
          <span className="text-ink-500">
            {offset + 1}-{Math.min(offset + limit, data.total)} из {data.total}
          </span>
          <Link
            href={buildUrl(offset + limit)}
            aria-disabled={offset + limit >= data.total}
            className={offset + limit >= data.total ? "pointer-events-none opacity-30" : "hover:text-ink-50"}
          >
            Старее →
          </Link>
        </div>
      )}
    </Container>
  );
}
