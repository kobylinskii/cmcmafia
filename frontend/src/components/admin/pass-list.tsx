"use client";

import { useState } from "react";
import { CaretDown, CaretRight, Copy, IdentificationCard } from "@phosphor-icons/react/dist/ssr";
import { ApiError, clientFetch } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { TimeField } from "@/components/ui/date-field";
import { Badge } from "@/components/ui/badge";
import {
  GAME_TYPE_LABELS,
  PASS_LIST_ROLE_LABELS,
  WEEKDAY_LABELS,
  type PassListOut,
  type PassWeekSettings,
} from "@/types/api";

/** Кому из записавшихся на игры недели нужен пропуск на ВМК.
 *
 * Неделя здесь не календарная: список переключается на наступающую в клубный
 * рубеж (по умолчанию воскресенье 18:00), чтобы заявку на пропуска успели
 * подать. Сам рубеж настраивается тут же -- менять его должен админ, а не
 * деплой.
 */
export function PassList() {
  const [open, setOpen] = useState(false);
  const { data, error, reload } = useResource<PassListOut>(
    open ? "/api/admin/pass-list" : null,
    "Не удалось загрузить список"
  );
  const [copyError, setCopyError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [editingRollover, setEditingRollover] = useState(false);

  async function copyNames() {
    if (!data) return;
    const text = data.entries.map((e) => e.full_name || e.nickname).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyError("Браузер не дал доступ к буферу обмена — скопируйте список вручную");
    }
  }

  return (
    <section className="mt-10">
      <h2 className="flex items-center gap-2 font-display text-lg text-ink-50">
        <IdentificationCard size={18} className="text-brand-400" />
        Нужен пропуск
      </h2>
      <p className="mt-1 text-sm text-ink-400">
        ФИО тех, кто указал «Вне МГУ, нужен пропуск» и записан хотя бы на одну фановую или
        обучающую игру этой недели.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="secondary" className="!px-4 !py-2" onClick={() => setOpen((v) => !v)}>
          {open ? <CaretDown size={16} /> : <CaretRight size={16} />}
          {open ? "Скрыть список" : "Показать список"}
        </Button>
        {open && data && (
          <>
            <Button
              variant="secondary"
              className="!px-4 !py-2"
              onClick={copyNames}
              disabled={data.entries.length === 0}
            >
              <Copy size={16} />
              {copied ? "Скопировано" : "Скопировать ФИО"}
            </Button>
            <Button variant="ghost" className="!px-4 !py-2" onClick={reload}>
              Обновить
            </Button>
          </>
        )}
      </div>

      {(error || copyError) && (
        <p className="mt-3 text-sm text-brand-300">{error || copyError}</p>
      )}

      {open && (
        <div className="mt-4">
          {data === null && !error && <p className="text-sm text-ink-500">Загрузка…</p>}

          {data && (
            <>
              <div className="rounded-card border border-ink-800 bg-ink-900 p-5">
                <p className="text-sm text-ink-200">
                  Неделя с {formatDateTime(data.week_start)} по {formatDateTime(data.week_end)}
                </p>
                <p className="mt-1 text-xs text-ink-500">
                  Список переключится на следующую неделю в{" "}
                  {WEEKDAY_LABELS[data.rollover_weekday]?.toLowerCase()} в {data.rollover_time}.{" "}
                  <button
                    type="button"
                    onClick={() => setEditingRollover((v) => !v)}
                    className="text-brand-300 underline underline-offset-2 hover:text-brand-200"
                  >
                    {editingRollover ? "Свернуть" : "Изменить"}
                  </button>
                </p>

                {editingRollover && (
                  <RolloverForm
                    initial={{
                      pass_week_rollover_weekday: data.rollover_weekday,
                      pass_week_rollover_time: data.rollover_time,
                    }}
                    onSaved={() => {
                      setEditingRollover(false);
                      reload();
                    }}
                  />
                )}
              </div>

              {data.entries.length === 0 ? (
                <p className="mt-3 rounded-card border border-ink-800 bg-ink-900 p-5 text-sm text-ink-500">
                  На этой неделе пропуск никому не нужен.
                </p>
              ) : (
                <ol className="mt-3 flex flex-col gap-2">
                  {data.entries.map((entry, index) => (
                    <li
                      key={entry.player_id}
                      className="rounded-card border border-ink-800 bg-ink-900 p-4"
                    >
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="text-xs text-ink-600">{index + 1}.</span>
                        <span className="text-sm text-ink-50">{entry.full_name || "ФИО не указано"}</span>
                        <span className="text-xs text-ink-500">{entry.nickname}</span>
                        {entry.confirmation_status !== "confirmed" && (
                          <Badge tone="outline">
                            {entry.confirmation_status === "pending" ? "На проверке" : "Отклонён"}
                          </Badge>
                        )}
                      </div>
                      <ul className="mt-2 flex flex-col gap-0.5 pl-6 text-xs text-ink-400">
                        {entry.games.map((game) => (
                          <li key={`${game.game_id}-${game.role}`}>
                            {formatDateTime(game.starts_at)} · {GAME_TYPE_LABELS[game.game_type]} ·{" "}
                            {PASS_LIST_ROLE_LABELS[game.role]}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function RolloverForm({
  initial,
  onSaved,
}: {
  initial: PassWeekSettings;
  onSaved: () => void;
}) {
  const [weekday, setWeekday] = useState(initial.pass_week_rollover_weekday);
  const [time, setTime] = useState(initial.pass_week_rollover_time);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await clientFetch<PassWeekSettings>("/api/admin/settings/pass-week", {
        method: "PUT",
        body: JSON.stringify({
          pass_week_rollover_weekday: weekday,
          pass_week_rollover_time: time,
        }),
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-ink-800 pt-4">
      <label className="flex flex-col gap-1.5 text-xs text-ink-400">
        День обновления
        <Select
          value={String(weekday)}
          onChange={(v) => setWeekday(Number(v))}
          className="rounded-lg border border-ink-700 bg-ink-950 px-3.5 py-2.5 text-sm text-ink-50 focus:border-brand-500 focus:outline-none"
          options={WEEKDAY_LABELS.map((label, index) => ({ value: String(index), label }))}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-xs text-ink-400">
        Время
        <TimeField
          value={time}
          onChange={setTime}
          className="rounded-lg border border-ink-700 bg-ink-950 px-3.5 py-2.5 text-sm text-ink-50 focus:border-brand-500 focus:outline-none"
        />
      </label>
      <Button className="!px-4 !py-2" onClick={save} disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
      {error && <p className="text-sm text-brand-300">{error}</p>}
    </div>
  );
}
