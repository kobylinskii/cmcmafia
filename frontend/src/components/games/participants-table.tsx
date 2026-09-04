import Link from "next/link";
import type { ParticipantOut } from "@/types/api";
import { ROLE_LABELS, INFO_LABELS } from "@/types/api";
import { formatDash } from "@/lib/format";

const th = "px-3 py-2.5 text-left text-xs font-medium text-ink-400 whitespace-nowrap";
const td = "px-3 py-2.5 text-sm text-ink-100 whitespace-nowrap";

export function ParticipantsTable({ participants }: { participants: ParticipantOut[] }) {
  const rows = [...participants].sort((a, b) => a.seat_number - b.seat_number);

  return (
    <div className="overflow-x-auto rounded-card border border-ink-800">
      <table className="w-full min-w-[880px] border-collapse">
        <thead>
          <tr className="border-b border-ink-800 bg-ink-900">
            <th className={th} rowSpan={2}>
              №
            </th>
            <th className={th} rowSpan={2}>
              Игрок
            </th>
            <th className={th} rowSpan={2}>
              Роль
            </th>
            <th className={`${th} text-center border-l border-ink-800`} colSpan={2}>
              Баллы победа + судьи
            </th>
            <th className={`${th} text-center border-l border-ink-800`} rowSpan={2}>
              ЛХ
            </th>
            <th className={`${th} text-center`} rowSpan={2}>
              Ci
            </th>
            <th className={`${th} text-center border-l border-ink-800`} rowSpan={2}>
              Инфо
            </th>
            <th className={`${th} text-center`} rowSpan={2}>
              Удаления
            </th>
            <th className={`${th} text-center border-l border-ink-800`} rowSpan={2}>
              ЖК
            </th>
            <th className={`${th} text-center`} rowSpan={2}>
              СК
            </th>
          </tr>
          <tr className="border-b border-ink-800 bg-ink-900">
            <th className={`${th} text-center border-l border-ink-800`}>За победу</th>
            <th className={`${th} text-center`}>От судей</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {rows.map((p) => (
            <tr key={p.seat_number} className="odd:bg-ink-900/40">
              <td className={`${td} font-mono text-ink-400`}>{p.seat_number}</td>
              <td className={td}>
                <Link href={`/mafia/${p.player_slug}`} className="font-medium text-ink-50 hover:text-brand-400">
                  {p.player_nickname}
                </Link>
              </td>
              <td className={td}>{ROLE_LABELS[p.role]}</td>
              <td className={`${td} text-center border-l border-ink-800 font-mono`}>{formatDash(p.points_win)}</td>
              <td className={`${td} text-center font-mono`}>{formatDash(p.points_judge)}</td>
              <td className={`${td} text-center border-l border-ink-800 font-mono`}>{formatDash(p.lh)}</td>
              <td className={`${td} text-center font-mono`}>{formatDash(p.ci)}</td>
              <td className={`${td} text-center border-l border-ink-800`}>
                {p.info ? INFO_LABELS[p.info] : "—"}
              </td>
              <td className={`${td} text-center font-mono`}>{p.removals ?? "—"}</td>
              <td className={`${td} text-center border-l border-ink-800 font-mono`}>{formatDash(p.zk)}</td>
              <td className={`${td} text-center font-mono`}>{formatDash(p.sk)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
