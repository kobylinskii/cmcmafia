"use client";

import { useEffect, useMemo, useState } from "react";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { fromClubDatetimeLocal, formatTime, plural } from "@/lib/format";
import { fieldDense as field, fieldLabel as label } from "@/lib/ui";
import type { ScheduleGameType, SchedulePlanPreviewOut, SessionOut } from "@/types/api";
import { GAME_TYPE_LABELS, SCHEDULE_GAME_TYPES } from "@/types/api";

// Границы шага повторяют backend/app/schemas/schedule.py: короче получаса игра
// не заканчивается, а полсуток -- это уже опечатка в поле.
const MIN_STEP = 30;
const MAX_STEP = 720;
const MAX_COUNT = 48;

/**
 * Планирование игрового дня: одна форма вместо шести экранов бота.
 *
 * Бот умел ровно «по игре на каждый целый час внутри диапазона», и вечер из
 * трёх игр по 75 минут в эту сетку не ложился: шаг и количество здесь заданы
 * явно. Пересечения по времени показываются до сохранения -- отдельной ручкой
 * предпросмотра, потому что узнать про занятое время из отказа на сохранении
 * значит потерять всё заполненное.
 */
export function PlanForm({
  locations,
  onCreated,
  onCancel,
}: {
  locations: string[];
  onCreated: (created: SessionOut[]) => void;
  onCancel: () => void;
}) {
  const [gameType, setGameType] = useState<ScheduleGameType>("funky");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("18:00");
  const [count, setCount] = useState("3");
  const [step, setStep] = useState("60");
  const [location, setLocation] = useState(locations[0] ?? "");
  const [needsRating, setNeedsRating] = useState(true);

  const [preview, setPreview] = useState<{ key: string; data: SchedulePlanPreviewOut } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  /** Времена будущих слотов -- всё, от чего зависит предпросмотр. Место,
   * формат и флаг оценки сюда не входят: на расстановку по времени они не
   * влияют, а в зависимостях эффекта заставляли бы перезапрашивать конфликты
   * на каждую букву в поле «Место». */
  const timing = useMemo(() => {
    const parsedCount = Number(count);
    const parsedStep = Number(step);
    if (!date || !time) return null;
    if (!Number.isInteger(parsedCount) || parsedCount < 1 || parsedCount > MAX_COUNT) return null;
    if (!Number.isInteger(parsedStep) || parsedStep < MIN_STEP || parsedStep > MAX_STEP) return null;
    return {
      // Поле заполнено клубным временем, и читать его надо тоже как клубное --
      // иначе админ не из Москвы сдвигал бы весь день каждым сохранением.
      starts_at: fromClubDatetimeLocal(`${date}T${time}`),
      count: parsedCount,
      step_minutes: parsedStep,
    };
  }, [date, time, count, step]);

  const payload = useMemo(
    () =>
      timing && {
        ...timing,
        location: location.trim(),
        game_type: gameType,
        needs_rating: needsRating,
      },
    [timing, location, gameType, needsRating]
  );

  // Предпросмотр обновляется сам, но с задержкой: иначе каждое нажатие в поле
  // «сколько игр» стоило бы запроса к API. Ответ помечен запросом, которому
  // принадлежит: медленный ответ на прежние значения иначе перерисовал бы
  // список времён поверх уже поправленных.
  useEffect(() => {
    if (!timing) return;
    const key = JSON.stringify(timing);
    // location и game_type обязательны для схемы запроса, но на времена не
    // влияют -- подставляем заглушки, чтобы предпросмотр работал ещё до того,
    // как заполнено место.
    const body = { ...timing, location: "—", game_type: "funky" };
    const timer = setTimeout(() => {
      clientFetch<SchedulePlanPreviewOut>("/api/admin/schedule/plan/preview", {
        method: "POST",
        body: JSON.stringify(body),
      })
        .then((data) => setPreview({ key, data }))
        .catch(() => undefined);
    }, 400);
    return () => clearTimeout(timer);
  }, [timing]);

  const shown = timing && preview?.key === JSON.stringify(timing) ? preview.data : null;
  const conflicts = useMemo(() => new Set(shown?.conflicts ?? []), [shown]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!payload) {
      setError("Заполните дату, время, количество игр и шаг между ними.");
      return;
    }
    if (!payload.location) {
      setError("Укажите место проведения.");
      return;
    }
    setSaving(true);
    try {
      const created = await clientFetch<SessionOut[]>("/api/admin/schedule/plan", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось создать игры");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-card border border-ink-800 bg-ink-900 p-5">
      <h2 className="font-display text-lg text-ink-50">Запланировать игры</h2>
      <p className="mt-1 text-xs text-ink-500">
        Создаётся столько слотов, сколько указано, начиная с первого времени и дальше через
        выбранный шаг. Записываются на них в боте.
      </p>

      <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className={label}>
          Формат
          <select
            className={field}
            value={gameType}
            onChange={(e) => setGameType(e.target.value as ScheduleGameType)}
          >
            {SCHEDULE_GAME_TYPES.map((value) => (
              <option key={value} value={value}>
                {GAME_TYPE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        <label className={label}>
          Дата
          <input
            type="date"
            className={field}
            value={date}
            onChange={(e) => setDate(e.target.value)}
            required
          />
        </label>
        <label className={label}>
          Начало первой игры
          <input
            type="time"
            className={field}
            value={time}
            onChange={(e) => setTime(e.target.value)}
            required
          />
        </label>
        <label className={label}>
          Сколько игр
          <input
            type="number"
            className={field}
            min={1}
            max={MAX_COUNT}
            value={count}
            onChange={(e) => setCount(e.target.value)}
            required
          />
        </label>
        <label className={label}>
          Шаг между играми, минут
          <input
            type="number"
            className={field}
            min={MIN_STEP}
            max={MAX_STEP}
            step={5}
            value={step}
            onChange={(e) => setStep(e.target.value)}
            required
          />
        </label>
        <label className={label}>
          Место
          {/* Список прошлых мест, но поле остаётся свободным: «ВМК МГУ, ауд.
              685» не должно набираться руками каждый игровой день, а новая
              аудитория не должна требовать правки кода. */}
          <input
            className={field}
            list="schedule-locations"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="ВМК МГУ, ауд. 685"
            maxLength={200}
            required
          />
          <datalist id="schedule-locations">
            {locations.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </label>
      </div>

      <label className="mt-5 flex cursor-pointer items-start gap-2.5 text-sm text-ink-200">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-brand-600"
          checked={needsRating}
          onChange={(e) => setNeedsRating(e.target.checked)}
        />
        <span>
          Игра будет оцениваться
          <span className="mt-0.5 block text-xs font-normal text-ink-500">
            {needsRating
              ? "После игры её нужно будет отметить проведённой — она уйдёт во вкладку «Ждут оценки», её результат попадёт в рейтинг."
              : "Слот нужен только для записи в боте: подтверждать проведение не потребуется, в «Ждут оценки» игра не попадёт и уйдёт из расписания сама."}
          </span>
        </span>
      </label>

      {shown && shown.starts_at_list.length > 0 && (
        <div className="mt-5">
          <p className="text-xs font-medium text-ink-400">
            Будет создано: {shown.starts_at_list.length}{" "}
            {plural(shown.starts_at_list.length, ["игра", "игры", "игр"])}
          </p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {shown.starts_at_list.map((iso) => {
              const busy = conflicts.has(iso);
              return (
                <li
                  key={iso}
                  className={
                    busy
                      ? "rounded-pill border border-brand-700 bg-brand-900/40 px-3 py-1 text-xs text-brand-200"
                      : "rounded-pill border border-ink-700 bg-ink-850 px-3 py-1 text-xs text-ink-200"
                  }
                >
                  {formatTime(iso)}
                  {busy && " · занято"}
                </li>
              );
            })}
          </ul>
          {conflicts.size > 0 && (
            <p className="mt-2 text-xs text-brand-300">
              На отмеченное время игры уже созданы. Сдвиньте начало или шаг — иначе сохранение не
              пройдёт.
            </p>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="mt-4 rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200">
          {error}
        </p>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <Button type="submit" disabled={saving} className="!px-5 !py-2.5">
          {saving ? "Создаём…" : "Создать игры"}
        </Button>
        <Button type="button" variant="secondary" className="!px-5 !py-2.5" onClick={onCancel}>
          Отмена
        </Button>
      </div>
    </form>
  );
}
