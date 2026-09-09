"use client";

import { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarBlank, CaretLeft, CaretRight, Clock } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { popupStyle, useAnchoredPopup } from "@/lib/use-anchored-popup";
import { toDateValue } from "@/lib/format";

/**
 * Календарь и часы вместо <input type="date"|"time"|"datetime-local">.
 * Нативные поля открывают диалог операционной системы -- на телефоне это
 * гугловский светло-серый календарь поверх тёмного сайта, и стилизовать его
 * нельзя. Значения снаружи те же, что у нативных полей: «ГГГГ-ММ-ДД»,
 * «ЧЧ:ММ» и «ГГГГ-ММ-ДДTЧЧ:ММ», поэтому формы и хелперы формата
 * (fromClubDatetimeLocal и компания) остались без изменений.
 */

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const POPUP_HEIGHT = 340;

/** Разбор «ГГГГ-ММ-ДД» без new Date(): строка -- клубная дата, а Date увёл бы
 * её на сутки в браузере с отрицательным смещением. */
function parseDate(value: string) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return m ? { year: Number(m[1]), month: Number(m[2]) - 1, day: Number(m[3]) } : null;
}

function toIso(year: number, month: number, day: number) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function todayIso() {
  return toDateValue(new Date().toISOString());
}

function monthLabel(year: number, month: number) {
  return new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(year, month, 1))
  );
}

const triggerBase =
  "flex w-full items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:text-ink-500";

export function DateField({
  value,
  onChange,
  min,
  max,
  className,
  clearable,
  id,
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  className?: string;
  /** Показывать «Очистить»: у фильтров дата необязательна, в формах -- нет. */
  clearable?: boolean;
  id?: string;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = parseDate(value);
  const [view, setView] = useState(() => selected ?? parseDate(todayIso())!);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);
  const rect = useAnchoredPopup({
    open,
    anchorRef: buttonRef,
    popupRef,
    onClose: close,
    maxHeight: POPUP_HEIGHT,
    minWidth: 300,
  });

  function openCalendar() {
    // Месяц показываем тот, что в поле: иначе после сохранения и повторного
    // открытия календарь висел бы на месяце, оставшемся с прошлого раза.
    setView(parseDate(value) ?? parseDate(todayIso())!);
    setOpen(true);
  }

  function choose(iso: string) {
    onChange(iso);
    setOpen(false);
    buttonRef.current?.focus();
  }

  const daysInMonth = new Date(Date.UTC(view.year, view.month + 1, 0)).getUTCDate();
  // getUTCDay() считает от воскресенья, а неделя в календаре начинается с понедельника.
  const leading = (new Date(Date.UTC(view.year, view.month, 1)).getUTCDay() + 6) % 7;
  const today = todayIso();

  function shiftMonth(delta: number) {
    const d = new Date(Date.UTC(view.year, view.month + delta, 1));
    setView({ year: d.getUTCFullYear(), month: d.getUTCMonth(), day: 1 });
  }

  return (
    <>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => (open ? setOpen(false) : openCalendar())}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className={clsx(triggerBase, className)}
      >
        <span className={selected ? undefined : "text-ink-500"}>
          {selected ? `${String(selected.day).padStart(2, "0")}.${String(selected.month + 1).padStart(2, "0")}.${selected.year}` : "дд.мм.гггг"}
        </span>
        <CalendarBlank size={16} className="shrink-0 text-ink-400" />
      </button>

      {open &&
        rect &&
        createPortal(
          <div
            ref={popupRef}
            role="dialog"
            aria-label="Выбор даты"
            style={popupStyle(rect, POPUP_HEIGHT)}
            className={clsx(
              "z-50 rounded-card border border-ink-700 bg-ink-850 p-3 shadow-xl",
              rect.openUp ? "mb-1" : "mt-1"
            )}
          >
            <div className="flex items-center justify-between">
              <button
                type="button"
                aria-label="Предыдущий месяц"
                onClick={() => shiftMonth(-1)}
                className="rounded-lg p-1.5 text-ink-300 hover:bg-ink-800 hover:text-ink-50"
              >
                <CaretLeft size={16} />
              </button>
              <span className="text-sm font-medium text-ink-100 first-letter:uppercase">
                {monthLabel(view.year, view.month)}
              </span>
              <button
                type="button"
                aria-label="Следующий месяц"
                onClick={() => shiftMonth(1)}
                className="rounded-lg p-1.5 text-ink-300 hover:bg-ink-800 hover:text-ink-50"
              >
                <CaretRight size={16} />
              </button>
            </div>

            <div className="mt-2 grid grid-cols-7 gap-0.5 text-center text-xs text-ink-500">
              {WEEKDAYS.map((w) => (
                <span key={w} className="py-1">
                  {w}
                </span>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-0.5">
              {Array.from({ length: leading }, (_, i) => <span key={`pad-${i}`} />)}
              {Array.from({ length: daysInMonth }, (_, i) => {
                const day = i + 1;
                const iso = toIso(view.year, view.month, day);
                // Границы -- лексикографическое сравнение «ГГГГ-ММ-ДД»: для
                // такого формата оно совпадает с хронологическим.
                const disabled = (min && iso < min) || (max && iso > max);
                return (
                  <button
                    key={day}
                    type="button"
                    disabled={Boolean(disabled)}
                    aria-current={iso === today ? "date" : undefined}
                    onClick={() => choose(iso)}
                    className={clsx(
                      "flex h-9 items-center justify-center rounded-lg text-sm",
                      iso === value
                        ? "bg-brand-600 font-medium text-white"
                        : disabled
                          ? "cursor-not-allowed text-ink-700"
                          : "text-ink-200 hover:bg-ink-800",
                      iso === today && iso !== value && "ring-1 ring-inset ring-ink-600"
                    )}
                  >
                    {day}
                  </button>
                );
              })}
            </div>

            <div className="mt-2 flex justify-between border-t border-ink-800 pt-2">
              <button
                type="button"
                onClick={() => choose(today)}
                className="rounded-lg px-2 py-1 text-xs text-ink-300 hover:text-ink-50"
              >
                Сегодня
              </button>
              {clearable && value && (
                <button
                  type="button"
                  onClick={() => choose("")}
                  className="rounded-lg px-2 py-1 text-xs text-ink-300 hover:text-ink-50"
                >
                  Очистить
                </button>
              )}
            </div>
          </div>,
          document.body
        )}
    </>
  );
}

const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, "0"));

/** Прокручивает выбранный пункт к середине своей колонки. scrollIntoView не
 * годится: он тянет за собой и страницу под открытой выпадашкой. */
function centerInColumn(el: HTMLButtonElement | null) {
  const column = el?.parentElement;
  if (el && column) column.scrollTop = el.offsetTop - column.clientHeight / 2 + el.clientHeight / 2;
}

export function TimeField({
  value,
  onChange,
  className,
  id,
  "aria-label": ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  id?: string;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setOpen(false), []);
  const rect = useAnchoredPopup({
    open,
    anchorRef: buttonRef,
    popupRef,
    onClose: close,
    maxHeight: POPUP_HEIGHT,
    minWidth: 176,
  });

  const [hour, minute] = value.split(":");
  // Шаг пять минут покрывает расписание клуба, но игра, заведённая раньше на
  // 19:07, не должна терять свою минуту при открытии списка.
  const minutes = minute && !MINUTES.includes(minute) ? [...MINUTES, minute].sort() : MINUTES;

  // Часы список не закрывают -- следом почти всегда выбирают минуты; минуты
  // закрывают, иначе на телефоне остаётся лишний тап мимо попапа.
  function pick(nextHour: string, nextMinute: string, done: boolean) {
    onChange(`${nextHour}:${nextMinute}`);
    if (done) {
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  return (
    <>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className={clsx(triggerBase, className)}
      >
        <span className={value ? undefined : "text-ink-500"}>{value || "чч:мм"}</span>
        <Clock size={16} className="shrink-0 text-ink-400" />
      </button>

      {open &&
        rect &&
        createPortal(
          <div
            ref={popupRef}
            role="dialog"
            aria-label="Выбор времени"
            style={popupStyle(rect, 232)}
            className={clsx(
              "z-50 grid grid-cols-2 gap-1 rounded-card border border-ink-700 bg-ink-850 p-1.5 shadow-xl",
              rect.openUp ? "mb-1" : "mt-1"
            )}
          >
            <div className="max-h-52 overflow-y-auto">
              {HOURS.map((h) => (
                <button
                  key={h}
                  type="button"
                  ref={h === hour ? centerInColumn : undefined}
                  onClick={() => pick(h, minute || "00", false)}
                  className={clsx(
                    "block w-full rounded-lg py-2 text-center text-sm",
                    h === hour ? "bg-brand-600 text-white" : "text-ink-200 hover:bg-ink-800"
                  )}
                >
                  {h}
                </button>
              ))}
            </div>
            <div className="max-h-52 overflow-y-auto">
              {minutes.map((m) => (
                <button
                  key={m}
                  type="button"
                  ref={m === minute ? centerInColumn : undefined}
                  onClick={() => pick(hour || "00", m, true)}
                  className={clsx(
                    "block w-full rounded-lg py-2 text-center text-sm",
                    m === minute ? "bg-brand-600 text-white" : "text-ink-200 hover:bg-ink-800"
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>,
          document.body
        )}
    </>
  );
}

/** Дата и время одним значением «ГГГГ-ММ-ДДTЧЧ:ММ» -- замена datetime-local. */
export function DateTimeField({
  value,
  onChange,
  className,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  id?: string;
}) {
  const [date = "", time = ""] = value.split("T");
  // Ширину задают обёртки, а не классы на самих кнопках: у триггера свой
  // w-full, и w-28 на нём проигрывал бы гонку специфичности.
  return (
    <div className="flex gap-2">
      <div className="min-w-0 flex-1">
        <DateField
          id={id}
          aria-label="Дата"
          value={date}
          onChange={(next) => onChange(`${next}T${time}`)}
          className={className}
        />
      </div>
      <div className="w-28 shrink-0">
        <TimeField
          aria-label="Время"
          value={time}
          onChange={(next) => onChange(`${date}T${next}`)}
          className={className}
        />
      </div>
    </div>
  );
}
