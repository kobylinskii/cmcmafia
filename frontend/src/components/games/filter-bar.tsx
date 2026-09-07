"use client";

import { useSearchParams } from "next/navigation";
import { useUpdateParams } from "@/lib/nav";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { GAME_TYPE_LABELS, type TournamentListItem } from "@/types/api";

const PAGE_SIZES = ["10", "25", "50", "100"].map((n) => ({ value: n, label: n }));

const control =
  "rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-base text-ink-100 focus:border-brand-500 focus:outline-none";
const fieldLabel = "flex flex-col gap-1.5 text-sm text-ink-400";

// Список турниров приходит пропом от серверного компонента страницы, а не
// догружается из браузера: иначе это лишний запрос на каждый заход, мигание
// «Турниров нет» до его завершения и лишняя зависимость публичной страницы от
// достижимости API с клиента.
export function GamesFilterBar({ tournaments }: { tournaments: TournamentListItem[] }) {
  const searchParams = useSearchParams();
  const update = useUpdateParams();

  const limit = searchParams.get("limit") ?? "10";
  const gameType = searchParams.get("game_type") ?? "";
  const tournamentSlug = searchParams.get("tournament_slug") ?? "";
  const dateFrom = searchParams.get("date_from") ?? "";
  const dateTo = searchParams.get("date_to") ?? "";
  const hasFilters = Boolean(gameType || tournamentSlug || dateFrom || dateTo);

  return (
    <div className="flex flex-col gap-6 rounded-card border border-ink-800 bg-ink-900 p-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className={fieldLabel}>
          Формат
          <select value={gameType} onChange={(e) => update({ game_type: e.target.value })} className={control}>
            <option value="">Все форматы</option>
            {Object.entries(GAME_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label className={fieldLabel}>
          Турнир
          <select
            value={tournamentSlug}
            onChange={(e) => update({ tournament_slug: e.target.value })}
            className={control}
            disabled={tournaments.length === 0}
          >
            <option value="">{tournaments.length ? "Все турниры" : "Турниров нет"}</option>
            {tournaments.map((tournament) => (
              <option key={tournament.slug} value={tournament.slug}>
                {tournament.name}
              </option>
            ))}
          </select>
        </label>

        <label className={fieldLabel}>
          Дата с
          <input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => update({ date_from: e.target.value })}
            className={control}
          />
        </label>

        <label className={fieldLabel}>
          Дата по
          <input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => update({ date_to: e.target.value })}
            className={control}
          />
        </label>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4 border-t border-ink-800 pt-5">
        <div className={fieldLabel}>
          Показывать последние
          <SegmentedControl
            options={PAGE_SIZES}
            value={limit}
            onChange={(limit) => update({ limit })}
          />
        </div>

        {hasFilters && (
          <button
            type="button"
            onClick={() =>
              update({ game_type: "", tournament_slug: "", date_from: "", date_to: "" })
            }
            className="rounded-pill border border-ink-700 px-4 py-2 text-sm font-medium text-ink-300 transition-colors hover:border-ink-500 hover:text-ink-50 active:translate-y-px"
          >
            Сбросить фильтры
          </button>
        )}
      </div>
    </div>
  );
}
