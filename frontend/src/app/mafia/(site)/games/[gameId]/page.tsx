import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, CalendarBlank, MapPin, Trophy } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api";
import { serverGet } from "@/lib/api-server";
import type { GameOut } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";
import { Container } from "@/components/ui/container";
import { ResultBadge, Badge } from "@/components/ui/badge";
import { ParticipantsTable } from "@/components/games/participants-table";
import { formatDateLong } from "@/lib/format";

// Рендер на каждый запрос, а не пререндер при сборке. Кеширование живёт
// уровнем ниже -- в serverGet, где у каждого запроса к API стоит
// next: { revalidate, tags } (см. lib/api-server.ts), и сбрасывается по тегу
// после правки в админке. Страничного revalidate здесь быть не должно: Next
// тогда пытается собрать страницу статически в момент `docker compose build`,
// где бэкенда ещё нет, и сборка падает на getaddrinfo ENOTFOUND api.
export const dynamic = "force-dynamic";

async function getGame(gameId: string): Promise<GameOut | null> {
  try {
    return await serverGet<GameOut>(`/api/games/${encodeURIComponent(gameId)}`);
  } catch (err) {
    // Любой 4xx -- это «такой игры нет», а не поломка сайта. Ловили только
    // 404, и /mafia/games/abc (422 от бэкенда) вместе с номером, не влезающим
    // в integer, отдавали посетителю жёсткую 500 -- достаточно было битой
    // ссылки из чата или краулера. Тот же разбор, что у limit/offset в
    // lib/search-params.ts.
    if (err instanceof ApiError && err.status >= 400 && err.status < 500) return null;
    throw err;
  }
}

export async function generateMetadata({
  params,
}: PageProps<"/mafia/games/[gameId]">): Promise<Metadata> {
  const { gameId } = await params;
  const game = await getGame(gameId);
  return { title: game ? `Игра №${game.id}` : "Игра не найдена" };
}

export default async function GameDetailPage({ params }: PageProps<"/mafia/games/[gameId]">) {
  const { gameId } = await params;
  const game = await getGame(gameId);
  if (!game) notFound();

  return (
    <Container className="py-14">
      <Link href="/mafia/games" className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100">
        <ArrowLeft size={16} />
        Все игры
      </Link>

      <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-medium text-ink-50 md:text-3xl">Игра №{game.id}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-300">
            <span className="inline-flex items-center gap-1.5">
              <CalendarBlank size={16} className="text-ink-400" />
              {formatDateLong(game.starts_at)}
            </span>
            {game.location && (
              <span className="inline-flex items-center gap-1.5">
                <MapPin size={16} className="text-ink-400" />
                {game.location}
              </span>
            )}
            {game.tournament && (
              <Link
                href={`/mafia/tournaments/${game.tournament.slug}`}
                className="inline-flex items-center gap-1.5 text-ink-200 hover:text-brand-300"
              >
                <Trophy size={16} className="text-ink-400" />
                {game.tournament.name}
              </Link>
            )}
            <Badge tone="outline">{GAME_TYPE_LABELS[game.game_type]}</Badge>
          </div>
        </div>
        <ResultBadge result={game.result} />
      </div>

      <div className="mt-8">
        <ParticipantsTable participants={game.participants} />
      </div>
    </Container>
  );
}
