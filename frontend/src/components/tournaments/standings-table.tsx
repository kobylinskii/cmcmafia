import Link from "next/link";
import { CheckCircle } from "@phosphor-icons/react/dist/ssr";
import type { TournamentStandingOut } from "@/types/api";
import { formatDash } from "@/lib/format";
import { PlayerAvatar } from "@/components/ui/player-avatar";

/**
 * Турнирная таблица: суммы игровых колонок по всем оценённым играм турнира
 * (или одного его этапа), один игрок -- одна строка, отсортировано бэкендом
 * по убыванию «Итог» (backend stats_service.tournament_standings). Это не
 * общий клубный рейтинг Эло (тот -- в /mafia/rating) и не среднее за игру, а
 * именно накопленная сумма -- как в турнирной таблице очков.
 */
export function TournamentStandingsTable({
  rows,
  showAdvanced = false,
}: {
  rows: TournamentStandingOut[];
  /** Колонка "Прошёл дальше" -- только внутри таблицы конкретного этапа,
   * где это вообще имеет смысл (см. страницу турнира). */
  showAdvanced?: boolean;
}) {
  if (rows.length === 0) {
    return (
      <p className="border-l-2 border-ink-700 py-4 pl-6 text-base text-ink-400">
        Пока нет оценённых партий — таблица появится после первой.
      </p>
    );
  }

  // Сумма очков сопоставима только когда все сыграли одинаковое число игр.
  // Инвариант «один состав во всех играх таблицы» бэкенд проверяет при оценке
  // игры, но данные могли попасть в базу и мимо этого пути -- тогда таблица,
  // отсортированная по сумме, молча ставила выше того, кто сыграл меньше.
  const unevenGames = new Set(rows.map((r) => r.games_count)).size > 1;

  return (
    <div className="flex flex-col gap-3">
      {unevenGames && (
        <p
          role="status"
          className="rounded-card border border-brand-800 bg-brand-900/25 px-4 py-3 text-sm leading-relaxed text-brand-100"
        >
          Участники сыграли разное число игр, поэтому сумма очков не позволяет
          сравнивать их напрямую — места в таблице условны.
        </p>
      )}
      <div className="overflow-x-auto rounded-card border border-ink-800">
      <table aria-label="Турнирная таблица" className="w-full min-w-[860px] border-collapse">
        <thead>
          <tr className="border-b border-ink-800 bg-ink-900 text-left text-xs font-medium text-ink-400">
            <th scope="col" className="px-4 py-3 w-12">#</th>
            <th scope="col" className="px-4 py-3">Игрок</th>
            <th scope="col" className="px-4 py-3 text-right">Игр</th>
            <th scope="col" className="px-4 py-3 text-right">За победу</th>
            <th scope="col" className="px-4 py-3 text-right">От судей</th>
            <th scope="col" className="px-4 py-3 text-right">ЛХ</th>
            <th scope="col" className="px-4 py-3 text-right">Ci</th>
            <th scope="col" className="px-4 py-3 text-right">Удаления</th>
            <th scope="col" className="px-4 py-3 text-right">ППК</th>
            <th scope="col" className="px-4 py-3 text-right">ЖК</th>
            <th scope="col" className="px-4 py-3 text-right">СК</th>
            <th scope="col" className="px-4 py-3 text-right border-l border-ink-800">Итог</th>
            {showAdvanced && <th scope="col" className="px-4 py-3 text-center border-l border-ink-800">Прошёл дальше</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {rows.map((row) => (
            <tr
              key={row.slug}
              className={
                showAdvanced && row.advanced
                  ? "bg-brand-900/15 hover:bg-brand-900/25"
                  : "odd:bg-ink-900/40 hover:bg-ink-850"
              }
            >
              <td className="px-4 py-3 font-mono text-sm text-ink-400">{row.rank}</td>
              <td className="px-4 py-3">
                <Link
                  href={`/mafia/${row.slug}`}
                  className="flex items-center gap-3 font-medium text-ink-50 hover:text-brand-400"
                >
                  <PlayerAvatar photoUrl={row.photo_url} nickname={row.nickname} />
                  {row.nickname}
                </Link>
              </td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{row.games_count}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.points_win)}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.points_judge)}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.lh_points)}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.ci)}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{row.removals}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{row.ppk_count}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.zk)}</td>
              <td className="px-4 py-3 text-right font-mono text-sm text-ink-300">{formatDash(row.sk)}</td>
              <td className="px-4 py-3 text-right border-l border-ink-800 font-mono text-sm font-semibold text-ink-50">
                {formatDash(row.total_score)}
              </td>
              {showAdvanced && (
                <td className="px-4 py-3 text-center border-l border-ink-800">
                  {row.advanced && (
                    <CheckCircle size={20} weight="fill" className="mx-auto text-brand-400" />
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
        </table>
      </div>
    </div>
  );
}
