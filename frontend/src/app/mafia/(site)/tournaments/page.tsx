import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight, MapPin, Trophy } from "@phosphor-icons/react/dist/ssr";
import { serverGet } from "@/lib/api-server";
import type { TournamentListItem } from "@/types/api";
import { Container } from "@/components/ui/container";
import { Reveal } from "@/components/reveal";

export const metadata: Metadata = {
  title: "Турниры",
  description: "Турниры клуба спортивной мафии ВМК МГУ: составы, площадки и сыгранные партии.",
};
// Рендер на каждый запрос, а не пререндер при сборке. Кеширование живёт
// уровнем ниже -- в serverGet, где у каждого запроса к API стоит
// next: { revalidate, tags } (см. lib/api-server.ts), и сбрасывается по тегу
// после правки в админке. Страничного revalidate здесь быть не должно: Next
// тогда пытается собрать страницу статически в момент `docker compose build`,
// где бэкенда ещё нет, и сборка падает на getaddrinfo ENOTFOUND api.
export const dynamic = "force-dynamic";

export default async function TournamentsPage() {
  const tournaments = await serverGet<TournamentListItem[]>("/api/tournaments");
  const totalGames = tournaments.reduce((sum, t) => sum + t.games_count, 0);

  return (
    <Container className="py-14">
      {/* Асимметричная шапка: заголовок слева, счётчики прижаты вправо и вниз --
          ровно по базовой линии, без центрирования. */}
      <div className="flex flex-col gap-6 border-b border-ink-800 pb-10 md:flex-row md:items-end md:justify-between">
        <div className="prose-measure">
          <h1 className="font-display text-3xl leading-tight font-medium text-ink-50 md:text-5xl md:tracking-tight">
            Турниры
          </h1>
          <p className="mt-4 text-base leading-relaxed text-ink-300">
            Турниры клуба со своими площадками, составами и таблицами.
          </p>
        </div>
        {tournaments.length > 0 && (
          <dl className="flex shrink-0 gap-10">
            <div>
              <dt className="text-sm text-ink-500">Турниров</dt>
              <dd className="font-mono text-3xl text-ink-50">{tournaments.length}</dd>
            </div>
            <div>
              <dt className="text-sm text-ink-500">Партий</dt>
              <dd className="font-mono text-3xl text-ink-50">{totalGames}</dd>
            </div>
          </dl>
        )}
      </div>

      {tournaments.length === 0 ? (
        <div className="mt-16 flex flex-col items-start gap-4 border-l-2 border-brand-700 pl-6">
          <Trophy size={30} weight="duotone" className="text-brand-400" />
          <p className="font-display text-xl text-ink-100">Турниров пока нет</p>
          <p className="prose-measure text-base leading-relaxed text-ink-400">
            Первый турнир появится здесь, когда его заведёт администратор.
          </p>
        </div>
      ) : (
        // Список с разделителями, а не сетка одинаковых карточек: турниры
        // читаются сверху вниз, и длина названия им не мешает.
        <ul className="mt-4 divide-y divide-ink-800">
          {tournaments.map((tournament, i) => (
            <Reveal key={tournament.slug} delay={Math.min(i, 6) * 0.05}>
              <li>
                <Link
                  href={`/mafia/tournaments/${tournament.slug}`}
                  className="group grid grid-cols-1 items-baseline gap-2 py-7 transition-colors md:grid-cols-[1fr_auto_auto] md:gap-8"
                >
                  <span className="flex items-baseline gap-3">
                    <span className="font-display text-xl text-ink-50 group-hover:text-brand-300 md:text-2xl">
                      {tournament.name}
                    </span>
                    <ArrowUpRight
                      size={18}
                      className="shrink-0 text-ink-600 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-brand-400"
                    />
                  </span>
                  {tournament.location && (
                    <span className="inline-flex items-center gap-1.5 text-base text-ink-400">
                      <MapPin size={16} className="text-ink-600" />
                      {tournament.location}
                    </span>
                  )}
                  <span className="font-mono text-base text-ink-300 md:text-right">
                    {tournament.games_count}
                    <span className="ml-1.5 font-sans text-sm text-ink-500">
                      {gamesWord(tournament.games_count)}
                    </span>
                  </span>
                </Link>
              </li>
            </Reveal>
          ))}
        </ul>
      )}
    </Container>
  );
}

function gamesWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "игра";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "игры";
  return "игр";
}
