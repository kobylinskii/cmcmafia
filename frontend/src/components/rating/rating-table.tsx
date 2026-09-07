import Link from "next/link";
import type { RatingRowOut } from "@/types/api";
import { formatPercent, formatDash } from "@/lib/format";
import { PlayerAvatar } from "@/components/ui/player-avatar";

export function RatingTable({ rows }: { rows: RatingRowOut[] }) {
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
            <th scope="col" className="px-4 py-3 text-right">Рейтинг</th>
            <th scope="col" className="px-4 py-3 text-right">Игр</th>
            <th scope="col" className="px-4 py-3 text-right">% побед</th>
            <th scope="col" className="px-4 py-3 text-right">Средний доп. балл</th>
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
                <Link href={`/mafia/${row.slug}`} className="flex items-center gap-3 font-medium text-ink-50 hover:text-brand-400">
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
