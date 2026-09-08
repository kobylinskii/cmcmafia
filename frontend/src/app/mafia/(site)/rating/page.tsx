import type { Metadata } from "next";
import { serverGet } from "@/lib/api-server";
import type { RatingFormulaOut, RatingSort, RatingTableOut } from "@/types/api";
import { Container } from "@/components/ui/container";
import { RatingTable } from "@/components/rating/rating-table";
import { RatingFormula } from "@/components/rating/rating-formula";
import { RatingSearchInput } from "@/components/rating/search-input";
import { ScrollToSection } from "@/components/scroll-to-section";
import { firstParam } from "@/lib/search-params";
import { withCount } from "@/lib/format";
import Link from "next/link";

export const metadata: Metadata = { title: "Рейтинг" };
// Рендер на каждый запрос, а не пререндер при сборке. Кеширование живёт
// уровнем ниже -- в serverGet, где у каждого запроса к API стоит
// next: { revalidate, tags } (см. lib/api-server.ts), и сбрасывается по тегу
// после правки в админке. Страничного revalidate здесь быть не должно: Next
// тогда пытается собрать страницу статически в момент `docker compose build`,
// где бэкенда ещё нет, и сборка падает на getaddrinfo ENOTFOUND api.
export const dynamic = "force-dynamic";

export default async function RatingPage({ searchParams }: PageProps<"/mafia/rating">) {
  const params = await searchParams;
  const q = firstParam(params, "q");
  // Раньше limit=100 был захардкожен без пагинации: 101-й игрок в рейтинге
  // просто переставал существовать для сайта.
  const limit = 50;
  const offset = Math.max(0, Number(firstParam(params, "offset") ?? 0) || 0);
  // Мусор в ?sort= роняет ручку 422, поэтому неизвестное значение просто
  // считается сортировкой по умолчанию.
  const rawSort = firstParam(params, "sort");
  const sort: RatingSort =
    rawSort === "games_count" || rawSort === "win_rate" || rawSort === "avg_bonus"
      ? rawSort
      : "rating";

  const [rating, formula] = await Promise.all([
    serverGet<RatingTableOut>("/api/rating", { q, limit, offset, sort }),
    serverGet<RatingFormulaOut>("/api/rating/formula"),
  ]);

  const buildUrl = (nextOffset: number, nextSort: RatingSort = sort) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (nextOffset > 0) p.set("offset", String(nextOffset));
    if (nextSort !== "rating") p.set("sort", nextSort);
    const qs = p.toString();
    return qs ? `/mafia/rating?${qs}` : "/mafia/rating";
  };
  // Смена сортировки всегда возвращает на первую страницу: 51-я строка
  // прежнего порядка в новом не значит ничего.
  const buildSortUrl = (nextSort: RatingSort) => buildUrl(0, nextSort);

  return (
    <Container className="py-14">
      {/* Кнопка «Подробнее о формуле» с главной просит доскроллить до
          разбора формулы -- см. components/home/formula-link.tsx. */}
      <ScrollToSection />
      <div className="max-w-2xl">
        <h1 className="font-display text-3xl font-medium text-ink-50 md:text-4xl">Рейтинг клуба</h1>
        <p className="mt-4 text-base leading-relaxed text-ink-300">
          Таблица клуба по системе Эло. Формула, коэффициенты и штрафы.
        </p>
      </div>

      <div className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-base text-ink-400">
          {withCount(rating.total, ["игрок", "игрока", "игроков"])} в рейтинге
        </p>
        <RatingSearchInput />
      </div>

      <div className="mt-4">
        <RatingTable rows={rating.items} sort={sort} sortUrl={buildSortUrl} />
      </div>

      {rating.total > limit && (
        <nav className="mt-8 flex items-center justify-between text-base text-ink-300">
          <Link
            href={buildUrl(Math.max(0, offset - limit))}
            aria-disabled={offset === 0}
            className={offset === 0 ? "pointer-events-none opacity-30" : "hover:text-ink-50"}
          >
            ← Выше
          </Link>
          <span className="text-ink-500">
            {offset + 1}–{Math.min(offset + limit, rating.total)} из {rating.total}
          </span>
          <Link
            href={buildUrl(offset + limit)}
            aria-disabled={offset + limit >= rating.total}
            className={offset + limit >= rating.total ? "pointer-events-none opacity-30" : "hover:text-ink-50"}
          >
            Ниже →
          </Link>
        </nav>
      )}

      <RatingFormula formula={formula} />
    </Container>
  );
}
