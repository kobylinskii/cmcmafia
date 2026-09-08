"use client";

import { useState } from "react";
import { CaretDown, CaretUp, Eye, EyeSlash, PencilSimple } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useResource } from "@/lib/use-resource";
import { fieldDense } from "@/lib/ui";
import { formatDash, formatPercent } from "@/lib/format";
import type { TournamentAwardOut, TournamentAwardsOut } from "@/types/api";

/**
 * Предпросмотр номинаций: посчитанные победители, статистика каждого и
 * возможность заменить кандидата вручную. Считает всё бэкенд
 * (app/services/awards_service.py) по играм финального (или единственного)
 * стола -- здесь только показ и правка.
 *
 * Блок раскрывается кнопкой и грузится только тогда (useResource с path=null):
 * страница турнира открывается в основном ради слотов и оценок, а расчёт
 * номинаций -- это ещё три запроса в базу на каждое такое открытие.
 *
 * Замена сохраняется сразу по выбору, без отдельной кнопки: ответ ручки
 * возвращает пересчитанный блок целиком, так что предпросмотр обновляется тем
 * же запросом, которым правка и сохранилась.
 */
export function TournamentAwardsPanel({ tournamentId }: { tournamentId: number }) {
  const url = `/api/admin/tournaments/${tournamentId}/awards`;
  const [open, setOpen] = useState(false);
  const { data, error, setData } = useResource<TournamentAwardsOut>(
    open ? url : null,
    "Не удалось загрузить номинации"
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function save(body: { published?: boolean; winners?: Record<string, string | null> }) {
    setSaving(true);
    setSaveError(null);
    try {
      setData(await clientFetch<TournamentAwardsOut>(url, { method: "PUT", body: JSON.stringify(body) }));
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-card border border-ink-800 bg-ink-900/60 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-ink-50">Номинации и победители</h2>
          <p className="mt-1 max-w-xl text-sm text-ink-400">
            Считаются по играм финального стола (у турнира без сеток — по единственной таблице).
            На сайте блок появляется только после публикации.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {open && data && (
            <Button
              type="button"
              variant="secondary"
              disabled={saving}
              onClick={() => save({ published: !data.published })}
              className="!px-4"
            >
              {data.published ? <EyeSlash size={16} /> : <Eye size={16} />}
              {data.published ? "Скрыть на сайте" : "Показать на сайте"}
            </Button>
          )}
          <Button
            type="button"
            variant="secondary"
            onClick={() => setOpen((v) => !v)}
            className="!px-4"
          >
            {open ? <CaretUp size={16} /> : <CaretDown size={16} />}
            {open ? "Свернуть" : "Предпросмотр"}
          </Button>
        </div>
      </div>

      {open && data && (
        <p className="mt-3 text-xs text-ink-500">
          Стол:{" "}
          <span className="text-ink-300">{data.table_name ?? "единственная таблица турнира"}</span>
          {" · "}
          Блок на сайте:{" "}
          <span className={data.published ? "text-emerald-300" : "text-ink-300"}>
            {data.published ? "показан" : "скрыт"}
          </span>
        </p>
      )}

      {open && error && <p className="mt-3 text-sm text-brand-300">{error}</p>}
      {open && saveError && <p className="mt-3 text-sm text-brand-300">{saveError}</p>}
      {open && data === null && !error && <p className="mt-4 text-sm text-ink-500">Загрузка…</p>}
      {open && data?.problem && <p className="mt-4 text-sm text-ink-500">{data.problem}</p>}

      {open && data && data.items.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {data.items.map((award) => (
            <AwardRow
              key={award.nomination}
              award={award}
              disabled={saving}
              onPick={(slug) => save({ winners: { [award.nomination]: slug } })}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function AwardRow({
  award,
  disabled,
  onPick,
}: {
  award: TournamentAwardOut;
  disabled: boolean;
  onPick: (slug: string | null) => void;
}) {
  // Пустое значение -- «как посчитано»: сама подстановка расчётного победителя
  // в select сделала бы ручную правку неотличимой от автоматической.
  const value = award.manual && award.winner ? award.winner.slug : "";
  const options = [
    { value: "", label: "Автоматически — по расчёту" },
    ...award.candidates.map((c) => ({
      value: c.slug,
      label: `${c.nickname} · ${formatDash(c.score)} · ${c.rank} место в таблице`,
    })),
  ];

  return (
    <li className="rounded-card border border-ink-800 bg-ink-900 px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className="text-sm text-ink-50">{award.title}</span>
        {award.manual && (
          <span className="inline-flex items-center gap-1 rounded-pill bg-brand-900/40 px-2 py-0.5 text-[11px] text-brand-300">
            <PencilSimple size={11} />
            вручную
          </span>
        )}
        <span className="text-xs text-ink-500">{award.formula}</span>
      </div>

      {award.winner ? (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-ink-500">
          <span className="font-display text-base text-ink-100">{award.winner.nickname}</span>
          <span className="font-mono text-ink-200">{formatDash(award.winner.score)}</span>
          <span>
            игр: <span className="font-mono text-ink-300">{award.winner.games_count}</span>
          </span>
          <span>
            побед: <span className="font-mono text-ink-300">{award.winner.wins}</span>
          </span>
          <span>
            поражений: <span className="font-mono text-ink-300">{award.winner.losses}</span>
          </span>
          <span>
            % побед:{" "}
            <span className="font-mono text-ink-300">{formatPercent(award.winner.win_rate)}</span>
          </span>
          <span>
            от судей:{" "}
            <span className="font-mono text-ink-300">{formatDash(award.winner.points_judge)}</span>
          </span>
          <span>
            ЛХ: <span className="font-mono text-ink-300">{formatDash(award.winner.lh_points)}</span>
          </span>
          <span>
            сумма:{" "}
            <span className="font-mono text-ink-300">{formatDash(award.winner.total_score)}</span>
          </span>
        </div>
      ) : (
        <p className="mt-2 text-xs text-ink-500">Кандидатов нет — на этой роли ещё никто не играл.</p>
      )}

      {award.candidates.length > 0 && (
        <div className="mt-2.5 max-w-md">
          <Select
            value={value}
            options={options}
            disabled={disabled}
            aria-label={`${award.title}: выбрать победителя`}
            onChange={(next) => onPick(next === "" ? null : next)}
            className={fieldDense}
          />
        </div>
      )}
    </li>
  );
}
