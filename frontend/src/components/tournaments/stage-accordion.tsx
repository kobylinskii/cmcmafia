"use client";

import Link from "next/link";
import { useState } from "react";
import { CaretDown, CaretUp, ListNumbers } from "@phosphor-icons/react/dist/ssr";
import type { TournamentStageDetailOut } from "@/types/api";
import { formatDateTime } from "@/lib/format";
import { ResultBadge } from "@/components/ui/badge";
import { TournamentStandingsTable } from "@/components/tournaments/standings-table";

/**
 * Этапы турнира на публичной странице -- каждый в своём сворачиваемом
 * окошке: по умолчанию свёрнуты, кроме финального (если он отмечен в
 * админке) -- его таблица сразу развёрнута. Открыть можно сколько угодно
 * сразу, они не эксклюзивны друг другу. Внутри развёрнутого этапа отдельной
 * кнопкой поднимается пронумерованный список его игр (сыгранные ведут на
 * карточку игры, ещё не сыгранные просто занимают номер в очереди).
 */
export function TournamentStageAccordion({ stages }: { stages: TournamentStageDetailOut[] }) {
  const [openIds, setOpenIds] = useState<Set<number>>(
    () => new Set(stages.filter((s) => s.is_final).map((s) => s.id))
  );
  const [gamesOpenIds, setGamesOpenIds] = useState<Set<number>>(new Set());

  function toggle(id: number) {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleGames(id: number) {
    setGamesOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-3">
      {stages.map((stage) => {
        const open = openIds.has(stage.id);
        const gamesOpen = gamesOpenIds.has(stage.id);
        return (
          <div key={stage.id} className="rounded-card border border-ink-800 bg-ink-900">
            <button
              type="button"
              onClick={() => toggle(stage.id)}
              className="flex w-full items-center gap-3 px-5 py-4 text-left"
            >
              {open ? (
                <CaretUp size={18} className="shrink-0 text-ink-500" />
              ) : (
                <CaretDown size={18} className="shrink-0 text-ink-500" />
              )}
              <span className="font-display text-lg text-ink-50">{stage.name}</span>
              {stage.is_final && (
                <span className="rounded-pill bg-brand-900/40 px-2.5 py-0.5 text-xs text-brand-300">
                  Финал
                </span>
              )}
            </button>

            {open && (
              <div className="border-t border-ink-800 px-5 py-5">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-ink-500">
                    Сумма баллов и штрафов по играм этого этапа, от большего к меньшему.
                    {stage.standings.some((r) => r.advanced) && " Отмечены прошедшие дальше."}
                  </p>
                  {stage.games.length > 0 && (
                    <button
                      type="button"
                      onClick={() => toggleGames(stage.id)}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-pill border border-ink-700 px-3 py-1.5 text-xs font-medium text-ink-300 hover:border-ink-500 hover:text-ink-50"
                    >
                      <ListNumbers size={15} />
                      {gamesOpen ? "Скрыть игры" : "Список игр"}
                    </button>
                  )}
                </div>

                <div className="mt-4">
                  <TournamentStandingsTable rows={stage.standings} showAdvanced />
                </div>

                {gamesOpen && (
                  <ul className="mt-4 flex flex-col gap-1.5">
                    {stage.games.map((game) => (
                      <li
                        key={game.id}
                        className="flex items-center gap-3 rounded-lg border border-ink-800 bg-ink-850 px-3.5 py-2 text-sm"
                      >
                        <span className="w-6 shrink-0 font-mono text-ink-500">{game.number}</span>
                        {game.status === "rated" ? (
                          <Link
                            href={`/mafia/games/${game.id}`}
                            className="flex flex-1 flex-wrap items-center gap-3 text-ink-200 hover:text-brand-300"
                          >
                            <span>{formatDateTime(game.starts_at)}</span>
                            <ResultBadge result={game.result} />
                          </Link>
                        ) : (
                          <span className="flex-1 text-ink-500">Ещё не сыграна</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
