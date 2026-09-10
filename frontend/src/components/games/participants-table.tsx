import Link from "next/link";
import type { ParticipantOut } from "@/types/api";
import { ROLE_LABELS, INFO_LABELS, lhPoints, participantScore } from "@/types/api";
import { formatDash } from "@/lib/format";

// Раздельные left/center-варианты, а не "${base} text-center" поверх базы с
// уже зашитым text-left: обе утилиты равны по специфичности, и какая из них
// побеждает в каскаде решает порядок объявлений в СГЕНЕРИРОВАННОМ css, а не
// порядок классов в JSX -- в этой сборке text-center идёт раньше text-left,
// поэтому центрированные заголовки реально уезжали влево ("Баллы" и все
// остальные, просто на однословных подписях сдвиг был не так заметен).
const thLeft = "px-3 py-2.5 text-left text-xs font-medium text-ink-400 whitespace-nowrap";
const thCenter = "px-3 py-2.5 text-center text-xs font-medium text-ink-400 whitespace-nowrap";
const td = "px-3 py-2.5 text-sm text-ink-100 whitespace-nowrap";
const tdCenter = `${td} text-center font-mono`;

export function ParticipantsTable({ participants }: { participants: ParticipantOut[] }) {
  const rows = [...participants].sort((a, b) => a.seat_number - b.seat_number);

  return (
    <div className="overflow-x-auto rounded-card border border-ink-800">
      <table aria-label="Участники игры, роли и баллы" className="w-full min-w-[1040px] border-collapse">
        <thead>
          <tr className="border-b border-ink-800 bg-ink-900">
            <th scope="col" className={thLeft} rowSpan={2}>
              №
            </th>
            <th scope="col" className={thLeft} rowSpan={2}>
              Игрок
            </th>
            <th scope="col" className={thLeft} rowSpan={2}>
              Роль
            </th>
            <th scope="colgroup" className={`${thCenter} border-l border-ink-800`} colSpan={2}>
              Баллы
            </th>
            <th scope="col" className={`${thCenter} border-l border-ink-800`} rowSpan={2}>
              ЛХ
            </th>
            <th scope="col" className={thCenter} rowSpan={2}>
              Ci
            </th>
            <th scope="col" className={`${thCenter} border-l border-ink-800`} rowSpan={2}>
              Инфо
            </th>
            <th scope="col" className={thCenter} rowSpan={2}>
              Удаления
            </th>
            <th scope="col" className={thCenter} rowSpan={2}>
              ППК
            </th>
            <th scope="col" className={`${thCenter} border-l border-ink-800`} rowSpan={2}>
              ЖК
            </th>
            <th scope="col" className={thCenter} rowSpan={2}>
              СК
            </th>
            <th scope="col" className={`${thCenter} border-l border-ink-800`} rowSpan={2}>
              Итог
            </th>
          </tr>
          <tr className="border-b border-ink-800 bg-ink-900">
            <th scope="col" className={`${thCenter} border-l border-ink-800`}>За победу</th>
            <th scope="col" className={thCenter}>От судей</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {rows.map((p) => (
            <tr key={p.seat_number} className="odd:bg-ink-900/40">
              <td className={`${td} font-mono text-ink-400`}>{p.seat_number}</td>
              <td className={td}>
                <Link href={`/${p.player_slug}`} className="font-medium text-ink-50 hover:text-brand-400">
                  {p.player_nickname}
                </Link>
              </td>
              <td className={td}>{ROLE_LABELS[p.role]}</td>
              <td className={`${tdCenter} border-l border-ink-800`}>{formatDash(p.points_win)}</td>
              <td className={tdCenter}>{formatDash(p.points_judge)}</td>
              {/* Баллы, не попадания: "2/3"/"3/3" точны для судьи, но здесь
                  таблица баллов, и ЛХ должен читаться в тех же единицах, что
                  соседние колонки. Распределение попаданий на профиле игрока
                  остаётся отдельным -- там различать 0/3 и 1/3 как раз важно.
                  Незаполненный ЛХ -- прочерк, а не ноль: иначе в одной строке
                  «0» в этой колонке и «—» в соседних значили одно и то же, и
                  записанный ноль было не отличить от пустого поля. */}
              <td className={`${tdCenter} border-l border-ink-800`}>
                {p.lh === null ? "—" : formatDash(lhPoints(p.lh))}
              </td>
              <td className={tdCenter}>{formatDash(p.ci)}</td>
              <td className={`${td} text-center border-l border-ink-800`}>
                {p.info ? INFO_LABELS[p.info] : "—"}
              </td>
              <td className={tdCenter}>{p.removals ?? "—"}</td>
              {/* ППК стоит рядом с остальными штрафами, потому что это штраф и
                  есть: минус SCORE_PENALTY_PPK в колонке «Итог»
                  (см. participantScore). Без этой колонки итог у нарушителя
                  просто не сходился с суммой остальных ячеек строки. */}
              <td className={tdCenter}>
                {p.ppk ? <span className="font-sans font-medium text-brand-300">да</span> : "—"}
              </td>
              <td className={`${tdCenter} border-l border-ink-800`}>{formatDash(p.zk)}</td>
              <td className={tdCenter}>{formatDash(p.sk)}</td>
              <td className={`${tdCenter} border-l border-ink-800 font-semibold text-ink-50`}>
                {formatDash(participantScore(p))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
