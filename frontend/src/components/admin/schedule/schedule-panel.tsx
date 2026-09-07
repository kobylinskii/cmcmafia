"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CalendarPlus, CaretRight, Warning } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatDateTime, formatTime, plural, withCount } from "@/lib/format";
import type { ScheduleDayOut, SessionOut } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";
import { PlanForm } from "@/components/admin/schedule/plan-form";
import { SessionCard } from "@/components/admin/schedule/session-card";

// Ведущий и двое судей сверх стола: те же HOST_LIMIT/JUDGE_LIMIT, которыми
// registration_service отбивает четвёртого желающего в штаб.
const STAFF_SEATS = 3;

/**
 * Планировщик игровых дней -- бывшая админка бота.
 *
 * Три экрана вместо шести ботовых: список дней, игры одного дня, карточка
 * игры. Наверху -- игры, которые ждут ответа «состоялась или нет»: наступление
 * времени само по себе ничего не говорит о том, собрался ли стол, и без
 * отдельного списка забытая игра не всплыла бы нигде.
 */
export function SchedulePanel({
  day,
  sessionId,
  onOpenDay,
  onOpenSession,
  onBackToDays,
}: {
  day: string | null;
  sessionId: number | null;
  onOpenDay: (day: string) => void;
  onOpenSession: (id: number) => void;
  onBackToDays: () => void;
}) {
  const [days, setDays] = useState<ScheduleDayOut[] | null>(null);
  const [awaiting, setAwaiting] = useState<SessionOut[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  // Игры дня хранятся вместе с днём, которому принадлежат: без этого при
  // переходе между днями секунду показывался чужой список.
  const [daySessions, setDaySessions] = useState<{ day: string; items: SessionOut[] } | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadOverview = useCallback(() => {
    clientFetch<ScheduleDayOut[]>("/api/admin/schedule/days")
      .then(setDays)
      .catch((err) => {
        setDays([]);
        setError(err instanceof ApiError ? err.message : "Не удалось загрузить расписание");
      });
    clientFetch<SessionOut[]>("/api/admin/schedule/awaiting-confirmation")
      .then(setAwaiting)
      .catch(() => setAwaiting([]));
  }, []);

  useEffect(() => {
    loadOverview();
    clientFetch<string[]>("/api/admin/schedule/locations")
      .then(setLocations)
      .catch(() => setLocations([]));
  }, [loadOverview]);

  const loadDay = useCallback((value: string) => {
    clientFetch<SessionOut[]>(`/api/admin/schedule/sessions?day=${encodeURIComponent(value)}`)
      .then((items) => setDaySessions({ day: value, items }))
      .catch(() => setDaySessions({ day: value, items: [] }));
  }, []);

  // sessionId в зависимостях намеренно: возврат из карточки игры должен
  // показывать день уже с учётом правки или удаления.
  useEffect(() => {
    if (day) loadDay(day);
  }, [day, sessionId, loadDay]);

  const reload = useCallback(() => {
    loadOverview();
    if (day) loadDay(day);
  }, [day, loadDay, loadOverview]);

  if (sessionId !== null) {
    return (
      // key заставляет карточку перемонтироваться при переходе между слотами:
      // иначе поля формы секунду показывали данные предыдущей игры.
      <SessionCard
        key={sessionId}
        sessionId={sessionId}
        locations={locations}
        onBack={() => (day ? onOpenDay(day) : onBackToDays())}
        onChanged={reload}
      />
    );
  }

  if (day !== null) {
    const shownDay = daySessions?.day === day ? daySessions.items : null;
    return (
      <div>
        <button
          onClick={onBackToDays}
          className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100"
        >
          <ArrowLeft size={16} />
          Все игровые дни
        </button>
        <h2 className="mt-3 font-display text-xl text-ink-50">Игры {day}</h2>

        <div className="mt-4 flex flex-col gap-2">
          {shownDay === null && <p className="text-sm text-ink-500">Загрузка…</p>}
          {shownDay?.length === 0 && (
            <p className="rounded-card border border-ink-800 bg-ink-900 p-6 text-center text-sm text-ink-500">
              В этом дне не осталось игр.
            </p>
          )}
          {shownDay?.map((session) => (
            <SessionRow key={session.id} session={session} onOpen={() => onOpenSession(session.id)} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {awaiting.length > 0 && (
        <div className="rounded-card border border-brand-800 bg-brand-900/20 p-4">
          <h2 className="flex items-center gap-2 text-sm font-medium text-ink-100">
            <Warning size={16} className="text-brand-400" />
            Подтвердите проведение
          </h2>
          <p className="mt-1 text-xs text-ink-400">
            Эти игры прошли, но никто не сказал, состоялись ли они. Подтверждённая уходит в «Ждут
            оценки», остальные удаляются вместе с записями.
          </p>
          <div className="mt-3 flex flex-col gap-2">
            {awaiting.map((session) => (
              <button
                key={session.id}
                onClick={() => onOpenSession(session.id)}
                className="flex items-center justify-between gap-3 rounded-lg border border-ink-800 bg-ink-900 px-4 py-2.5 text-left text-sm hover:border-brand-600/60"
              >
                <span className="text-ink-100">Игра №{session.id}</span>
                <span className="text-xs text-ink-500">
                  {formatDateTime(session.starts_at)} ·{" "}
                  {withCount(session.hosts + session.judges + session.players, [
                    "запись",
                    "записи",
                    "записей",
                  ])}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className={awaiting.length > 0 ? "mt-6" : ""}>
        {planning ? (
          <PlanForm
            locations={locations}
            onCancel={() => setPlanning(false)}
            onCreated={(created) => {
              setPlanning(false);
              reload();
              clientFetch<string[]>("/api/admin/schedule/locations")
                .then(setLocations)
                .catch(() => undefined);
              if (created.length > 0) onOpenDay(formatDate(created[0].starts_at));
            }}
          />
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-medium text-ink-300">Игровые дни</h2>
              <p className="mt-1 text-xs text-ink-500">
                Слоты, на которые идёт запись в боте. Оценённая игра из расписания уходит — её
                правят во вкладке «Оценённые».
              </p>
            </div>
            <Button type="button" className="!px-4 !py-2.5" onClick={() => setPlanning(true)}>
              <CalendarPlus size={16} />
              Запланировать
            </Button>
          </div>
        )}
      </div>

      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}

      <div className="mt-4 flex flex-col gap-2">
        {days === null && <p className="text-sm text-ink-500">Загрузка…</p>}
        {days?.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-6 text-center text-sm text-ink-500">
            Игровых дней пока нет.
          </p>
        )}
        {days?.map((card) => (
          <button
            key={card.day}
            onClick={() => onOpenDay(card.day)}
            className="flex items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-900 p-4 text-left hover:border-brand-600/60"
          >
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="text-ink-100">{card.day}</span>
              <span className="text-ink-500">
                {card.games_count} {plural(card.games_count, ["игра", "игры", "игр"])}
              </span>
              {card.types.map((type) => (
                <Badge key={type} tone="outline">
                  {GAME_TYPE_LABELS[type]}
                </Badge>
              ))}
              {card.awaiting_count > 0 && (
                <Badge tone="brand">Подтвердить: {card.awaiting_count}</Badge>
              )}
            </div>
            <CaretRight size={16} className="shrink-0 text-ink-500" />
          </button>
        ))}
      </div>
    </div>
  );
}

function SessionRow({ session, onOpen }: { session: SessionOut; onOpen: () => void }) {
  const registered = session.hosts + session.judges + session.players;
  const past = new Date(session.starts_at) <= new Date();
  return (
    <button
      onClick={onOpen}
      className="flex items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-900 p-4 text-left hover:border-brand-600/60"
    >
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-mono text-ink-100">{formatTime(session.starts_at)}</span>
        <span className="text-ink-500">Игра №{session.id}</span>
        <Badge tone="outline">{GAME_TYPE_LABELS[session.game_type]}</Badge>
        {!session.needs_rating && <Badge tone="neutral">Без оценки</Badge>}
        <span className="text-ink-500">
          {registered} из {session.max_players + STAFF_SEATS}
          {session.reserves > 0 && ` · резерв ${session.reserves}`}
        </span>
        {session.status === "played" && <Badge tone="brand">Ждёт оценки</Badge>}
        {past && session.needs_rating && session.status !== "played" && (
          <Badge tone="brand">Подтвердить</Badge>
        )}
      </div>
      <CaretRight size={16} className="shrink-0 text-ink-500" />
    </button>
  );
}
