import type { Metadata } from "next";
import Link from "next/link";
import { serverGet } from "@/lib/api";
import type { GameListOut } from "@/types/api";
import { Container } from "@/components/ui/container";
import { GamesFilterBar } from "@/components/games/filter-bar";
import { GameCard } from "@/components/games/game-card";
import { firstParam } from "@/lib/search-params";

export const metadata: Metadata = { title: "Игры" };
export const dynamic = "force-dynamic";

export default async function GamesPage({
  searchParams,
}: PageProps<"/mafia/games">) {
  const params = await searchParams;
  const limit = Number(firstParam(params, "limit") ?? 10);
  const offset = Number(firstParam(params, "offset") ?? 0);
  const game_type = firstParam(params, "game_type");
  const result = firstParam(params, "result");

  const data = await serverGet<GameListOut>("/api/games", { limit, offset, game_type, result });

  const buildUrl = (nextOffset: number) => {
    const p = new URLSearchParams();
    if (game_type) p.set("game_type", game_type);
    if (result) p.set("result", result);
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
        <GamesFilterBar />
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
