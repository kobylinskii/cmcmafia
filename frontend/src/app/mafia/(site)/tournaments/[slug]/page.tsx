import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, MapPin } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api";
import { serverGet } from "@/lib/api-server";
import type { GameListOut, TournamentDetailOut } from "@/types/api";
import { Container } from "@/components/ui/container";
import { GameCard } from "@/components/games/game-card";
import { TournamentStandingsTable } from "@/components/tournaments/standings-table";
import { TournamentStageAccordion } from "@/components/tournaments/stage-accordion";
import { plural } from "@/lib/format";

export const revalidate = 300;

async function getTournament(slug: string): Promise<TournamentDetailOut | null> {
  try {
    return await serverGet<TournamentDetailOut>(`/api/tournaments/${slug}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function generateMetadata({
  params,
}: PageProps<"/mafia/tournaments/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const data = await getTournament(slug);
  if (!data) return { title: "Турнир не найден" };
  return {
    title: data.tournament.name,
    description: data.tournament.description ?? undefined,
  };
}

export default async function TournamentPage({ params }: PageProps<"/mafia/tournaments/[slug]">) {
  const { slug } = await params;
  const data = await getTournament(slug);
  if (!data) notFound();

  const { tournament, games_count, standings, stages } = data;
  const games = await serverGet<GameListOut>("/api/games", {
    tournament_slug: slug,
    limit: 200,
  });

  return (
    <Container className="py-14">
      <Link
        href="/mafia/tournaments"
        className="inline-flex items-center gap-1.5 text-base text-ink-400 hover:text-ink-100"
      >
        <ArrowLeft size={17} />
        Все турниры
      </Link>

      <header className="mt-5 border-b border-ink-800 pb-10">
        <h1 className="font-display text-3xl leading-tight font-medium text-ink-50 md:text-5xl md:tracking-tight">
          {tournament.name}
        </h1>
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-base text-ink-400">
          {tournament.location && (
            <span className="inline-flex items-center gap-1.5">
              <MapPin size={17} className="text-ink-600" />
              {tournament.location}
            </span>
          )}
          <span className="font-mono text-ink-300">
            {games_count}
            <span className="ml-1.5 font-sans text-ink-500">
              {plural(data.games_count, ["сыгранная партия", "сыгранные партии", "сыгранных партий"])}
            </span>
          </span>
        </div>
        {tournament.description && (
          <p className="prose-measure mt-6 text-base leading-relaxed text-ink-300">
            {tournament.description}
          </p>
        )}
      </header>

      {stages.length > 0 ? (
        // Турнир с сеткой (>10 участников, отбор + финал по олимпийской
        // системе): у каждого этапа СВОЯ таблица. Одна общая сумма по всему
        // турниру складывала бы игроков, сыгравших разное число игр на
        // разных этапах, в одну строку -- ровно та проблема, ради которой
        // сетки и завели.
        <>
          <section className="mt-10">
            <h2 className="font-display text-xl text-ink-50">Этапы</h2>
            <div className="mt-4">
              <TournamentStageAccordion stages={stages} />
            </div>
          </section>
          {standings.length > 0 && (
            <section className="mt-10">
              <h2 className="font-display text-xl text-ink-50">Без этапа</h2>
              <p className="mt-1 text-sm text-ink-500">
                Игры турнира, ещё не отнесённые ни к одному этапу.
              </p>
              <div className="mt-4">
                <TournamentStandingsTable rows={standings} />
              </div>
            </section>
          )}
        </>
      ) : (
        <section className="mt-10">
          <h2 className="font-display text-xl text-ink-50">Турнирная таблица</h2>
          <p className="mt-1 text-sm text-ink-500">
            Сумма баллов и штрафов по всем оценённым играм турнира, от большего к меньшему.
          </p>
          <div className="mt-4">
            <TournamentStandingsTable rows={standings} />
          </div>
        </section>
      )}

      <section className="mt-10">
        <h2 className="font-display text-xl text-ink-50">Партии турнира</h2>
        <div className="mt-4 flex flex-col gap-3">
          {games.items.length === 0 ? (
            <p className="border-l-2 border-ink-700 py-4 pl-6 text-base text-ink-400">
              В этом турнире ещё нет оценённых партий.
            </p>
          ) : (
            games.items.map((game) => <GameCard key={game.id} game={game} />)
          )}
        </div>
      </section>
    </Container>
  );
}
