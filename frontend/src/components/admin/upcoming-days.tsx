"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CalendarCheck } from "@phosphor-icons/react/dist/ssr";
import { clientFetch } from "@/lib/api";
import { DayCard } from "@/components/admin/schedule/day-card";
import { toDateValue } from "@/lib/format";
import type { ScheduleDayOut } from "@/types/api";

/** Сколько ближайших дней показывать. Дальше горизонта планирования клуба
 * список превращается в стену, а нужен он, чтобы решить, добирать ли людей на
 * эту неделю. */
const SHOWN_DAYS = 6;

/**
 * Ближайшие игровые дни на обзоре: когда играем и насколько собрались.
 *
 * До этого узнать, набирается ли вечер, можно было только открыв «Игры →
 * Расписание» и провалившись в каждый день по очереди: в списке дней стояло
 * число игр, но не число записавшихся.
 */
export function UpcomingDays() {
  const router = useRouter();
  const [days, setDays] = useState<ScheduleDayOut[] | null>(null);

  useEffect(() => {
    clientFetch<ScheduleDayOut[]>("/api/admin/schedule/days")
      .then(setDays)
      .catch(() => setDays([]));
  }, []);

  // Прошедшие дни из расписания не уходят, пока в них есть что подтвердить, --
  // на дашборде они не нужны: он про то, что ещё предстоит.
  const today = toDateValue(new Date().toISOString());
  const upcoming = (days ?? [])
    .filter((card) => toDateValue(card.first_starts_at) >= today)
    .slice(0, SHOWN_DAYS);

  return (
    <div className="mt-10">
      <h2 className="flex items-center gap-2 font-display text-lg text-ink-50">
        <CalendarCheck size={18} className="text-brand-400" />
        Ближайшие игры
      </h2>
      <p className="mt-1 text-sm text-ink-400">
        Когда играем и сколько уже записалось. Нажмите на день, чтобы открыть его игры.
      </p>

      <div className="mt-4 flex flex-col gap-2">
        {days === null && <p className="text-sm text-ink-500">Загрузка…</p>}
        {days !== null && upcoming.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-5 text-sm text-ink-500">
            Впереди игр нет. Запланируйте игровой день — на него пойдёт запись в боте.
          </p>
        )}
        {upcoming.map((card) => (
          <DayCard
            key={card.day}
            card={card}
            onOpen={() =>
              router.push(`/admin/games?tab=schedule&day=${encodeURIComponent(card.day)}`)
            }
          />
        ))}
      </div>
    </div>
  );
}
