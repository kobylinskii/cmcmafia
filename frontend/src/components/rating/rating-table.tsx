import Link from "next/link";
import { CaretDown } from "@phosphor-icons/react/dist/ssr";
import type { RatingRowOut, RatingSort } from "@/types/api";
import { formatPercent, formatDash } from "@/lib/format";
import { PlayerAvatar } from "@/components/ui/player-avatar";

/**
 * Таблица рейтинга. Сортировка живёт в заголовках колонок, а не в отдельной
 * панели фильтров: три сортируемые величины и так подписаны в шапке, и
 * дублировать их выпадашкой сверху -- лишний элемент на странице.
 *
 * Место в колонке «#» от сортировки не зависит: это место в клубе по
 * рейтингу, его считает бэкенд оконной функцией (stats_service.rating_table).
 */
export function RatingTable({
  rows,
  sort = "rating",
  sortUrl,
}: {
  rows: RatingRowOut[];
  sort?: RatingSort;
  /** Ссылка на ту же страницу с другой сортировкой (строит страница). */
  sortUrl?: (sort: RatingSort) => string;
}) {
  if (rows.length === 0) {
    return (
      <p className="rounded-card border border-ink-800 bg-ink-900 p-8 text-center text-ink-400">
        Никого не нашли. Проверьте написание ника.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-card border border-ink-800">
      <table aria-label="Рейтинг игроков клуба" className="w-full min-w-[640px] border-collapse">
        <thead>
          <tr className="border-b border-ink-800 bg-ink-900 text-left text-xs font-medium text-ink-400">
            <th scope="col" className="px-4 py-3 w-14">#</th>
            <th scope="col" className="px-4 py-3">Игрок</th>
            <SortableHeader label="Рейтинг" column="rating" sort={sort} sortUrl={sortUrl} />
            <SortableHeader label="Игр" column="games_count" sort={sort} sortUrl={sortUrl} />
            <SortableHeader label="% побед" column="win_rate" sort={sort} sortUrl={sortUrl} />
            <SortableHeader label="Средний доп. балл" column="avg_bonus" sort={sort} sortUrl={sortUrl} />
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {rows.map((row) => (
            <tr key={row.slug} className="odd:bg-ink-900/40 hover:bg-ink-850">
              {/* Ещё не игравший попадает сюда только поиском по нику: места и
                  рейтинга у него нет, и печатать «#1 · 0» вместо них -- врать. */}
              <td className="px-4 py-3 font-mono text-sm text-ink-400">
                {row.games_count > 0 ? row.rank : "—"}
              </td>
              <td className="px-4 py-3">
                <Link href={`/mafia/${row.slug}`} className="-my-2 flex items-center gap-3 py-2 font-medium text-ink-50 hover:text-brand-400">
                  <PlayerAvatar photoUrl={row.photo_url} nickname={row.nickname} />
                  {row.nickname}
                </Link>
              </td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-50">
                {row.games_count > 0 ? Math.round(row.rating) : "—"}
              </td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{row.games_count}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatPercent(row.win_rate)}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.avg_bonus)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Заголовок сортируемой колонки: ссылка со стрелкой. У неактивной колонки
 * стрелка проступает только под курсором -- иначе шапка из трёх стрелок
 * выглядит как ошибка вёрстки. */
function SortableHeader({
  label,
  column,
  sort,
  sortUrl,
}: {
  label: string;
  column: RatingSort;
  sort: RatingSort;
  sortUrl?: (sort: RatingSort) => string;
}) {
  const active = sort === column;
  return (
    <th
      scope="col"
      aria-sort={active ? "descending" : "none"}
      className={`px-4 py-3 text-right ${active ? "text-ink-100" : ""}`}
    >
      {sortUrl ? (
        <Link
          href={sortUrl(column)}
          className="group inline-flex items-center gap-1 hover:text-ink-100"
          title={`Отсортировать по «${label}»`}
        >
          {label}
          <CaretDown
            size={11}
            weight="bold"
            className={active ? "text-brand-400" : "text-ink-600 opacity-0 group-hover:opacity-100"}
          />
        </Link>
      ) : (
        label
      )}
    </th>
  );
}
