"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowLeft, ArrowSquareOut, CalendarBlank, MapPin } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import type { TournamentAdminOut } from "@/types/api";
import { TournamentForm } from "@/components/admin/tournament-form";
import { TournamentStagesManager } from "@/components/admin/tournament-stages-manager";
import { TournamentAwardsPanel } from "@/components/admin/tournament-awards-panel";
import { formatDate, withCount } from "@/lib/format";

/**
 * Раньше страница была одной узкой колонкой: форма настроек, под ней игры, под
 * ними этапы -- и до рабочей части (ради которой сюда и заходят) приходилось
 * прокручивать мимо шести полей, которые заполняются один раз при создании.
 * Теперь настройки -- закреплённая панель сбоку, а справа сразу видно то, с чем
 * админ работает каждый день. На узком экране всё складывается в прежний
 * вертикальный порядок.
 */
export default function EditTournamentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [tournament, setTournament] = useState<TournamentAdminOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    clientFetch<TournamentAdminOut>(`/api/admin/tournaments/${id}`)
      .then(setTournament)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }, [id]);

  return (
    <div>
      <Link
        href="/mafia/admin/tournaments"
        className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100"
      >
        <ArrowLeft size={16} />
        Турниры
      </Link>

      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h1 className="font-display text-2xl text-ink-50">
          {tournament ? tournament.name : "Загрузка…"}
        </h1>
        {tournament && (
          <a
            href={`/mafia/tournaments/${tournament.slug}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-brand-300"
          >
            Открыть на сайте
            <ArrowSquareOut size={14} />
          </a>
        )}
      </div>

      {/* Сводка тем, что уже заполнено: даты и место повторяются в форме слева,
          но там их надо искать глазами среди полей ввода. */}
      {tournament && (
        <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-ink-400">
          <span className="inline-flex items-center gap-1.5">
            <CalendarBlank size={14} />
            {formatDate(tournament.starts_at)} — {formatDate(tournament.ends_at)}
          </span>
          {tournament.location && (
            <span className="inline-flex items-center gap-1.5">
              <MapPin size={14} />
              {tournament.location}
            </span>
          )}
          <span className="font-mono text-ink-500">
            {withCount(tournament.games_count, ["оценённая игра", "оценённые игры", "оценённых игр"])}
          </span>
        </div>
      )}

      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}

      {tournament && (
        <div className="mt-8 grid grid-cols-1 items-start gap-8 xl:grid-cols-[minmax(340px,380px)_1fr]">
          {/* Панель настроек. Закреплена только там, где рядом есть рабочая
              колонка: на узком экране она просто первый блок в потоке.
              max-h + overflow -- на случай, когда форма выше окна, иначе
              sticky тихо перестаёт работать. */}
          <aside className="xl:sticky xl:top-6 xl:max-h-[calc(100vh-3rem)] xl:overflow-y-auto">
            <div className="rounded-card border border-ink-800 bg-ink-900/60 p-5">
              <h2 className="font-display text-base text-ink-50">Настройки турнира</h2>
              <p className="mt-1 text-xs leading-relaxed text-ink-500">
                Заполняются один раз при создании и меняются редко.
              </p>
              <div className="mt-5">
                <TournamentForm tournament={tournament} />
              </div>
            </div>
          </aside>

          <div className="min-w-0 flex flex-col gap-10">
            <TournamentStagesManager tournamentId={tournament.id} />
            <TournamentAwardsPanel tournamentId={tournament.id} />
          </div>
        </div>
      )}
    </div>
  );
}
