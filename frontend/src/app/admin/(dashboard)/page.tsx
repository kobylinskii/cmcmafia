"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CalendarPlus, ListChecks, UsersThree, Warning } from "@phosphor-icons/react/dist/ssr";
import { clientFetch } from "@/lib/api";
import type { GameListItem, SessionOut } from "@/types/api";
import { formatDateTime } from "@/lib/format";
import { PassList } from "@/components/admin/pass-list";

export default function AdminOverviewPage() {
  const [pending, setPending] = useState<GameListItem[] | null>(null);
  // Прошедшие игры, про которые ещё не сказано, состоялись ли они. Раньше этот
  // вопрос задавал бот; теперь единственный сигнал «что-то забыто» -- здесь и
  // во вкладке «Игры → Расписание».
  const [awaiting, setAwaiting] = useState<SessionOut[]>([]);

  useEffect(() => {
    clientFetch<GameListItem[]>("/api/admin/games/pending-review")
      .then(setPending)
      .catch(() => setPending([]));
    clientFetch<SessionOut[]>("/api/admin/schedule/awaiting-confirmation")
      .then(setAwaiting)
      .catch(() => setAwaiting([]));
  }, []);

  return (
    <div className="max-w-3xl">
      <h1 className="font-display text-2xl text-ink-50">Обзор</h1>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Link
          href="/admin/games?tab=schedule"
          className="flex items-center gap-3 rounded-card border border-ink-800 bg-ink-900 p-5 hover:border-brand-600/60"
        >
          <CalendarPlus size={22} className="text-brand-400" />
          <div>
            <p className="font-medium text-ink-50">Запланировать игры</p>
            <p className="text-xs text-ink-400">Игровой день для записи в боте</p>
          </div>
        </Link>
        <Link
          href="/admin/games/new"
          className="flex items-center gap-3 rounded-card border border-ink-800 bg-ink-900 p-5 hover:border-brand-600/60"
        >
          <ListChecks size={22} className="text-brand-400" />
          <div>
            <p className="font-medium text-ink-50">Добавить игру</p>
            <p className="text-xs text-ink-400">Новый результат по шаблону</p>
          </div>
        </Link>
        <Link
          href="/admin/players/new"
          className="flex items-center gap-3 rounded-card border border-ink-800 bg-ink-900 p-5 hover:border-brand-600/60"
        >
          <UsersThree size={22} className="text-brand-400" />
          <div>
            <p className="font-medium text-ink-50">Добавить игрока</p>
            <p className="text-xs text-ink-400">Профиль нового участника</p>
          </div>
        </Link>
      </div>

      {awaiting.length > 0 && (
        <div className="mt-10">
          <h2 className="flex items-center gap-2 font-display text-lg text-ink-50">
            <Warning size={18} className="text-brand-400" />
            Подтвердите проведение
          </h2>
          <p className="mt-1 text-sm text-ink-400">
            Эти игры прошли, но никто не ответил, состоялись ли они. Пока ответа нет, в «Ждут
            оценки» они не попадут.
          </p>
          <div className="mt-4 flex flex-col gap-2">
            {awaiting.map((session) => (
              <Link
                key={session.id}
                href={`/admin/games?tab=schedule&session=${session.id}`}
                className="flex items-center justify-between rounded-card border border-ink-800 bg-ink-900 p-4 hover:border-brand-600/60"
              >
                <span className="text-sm text-ink-100">Игра №{session.id}</span>
                <span className="text-xs text-ink-500">{formatDateTime(session.starts_at)}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="mt-10">
        <h2 className="flex items-center gap-2 font-display text-lg text-ink-50">
          <Warning size={18} className="text-brand-400" />
          Ждут оценки
        </h2>
        <p className="mt-1 text-sm text-ink-400">
          Игры, проведение которых подтвердили в расписании, но результат ещё не внесён.
        </p>

        <div className="mt-4 flex flex-col gap-2">
          {pending === null && <p className="text-sm text-ink-500">Загрузка…</p>}
          {pending?.length === 0 && (
            <p className="rounded-card border border-ink-800 bg-ink-900 p-5 text-sm text-ink-500">
              Пока нечего оценивать.
            </p>
          )}
          {pending?.map((game) => (
            <Link
              key={game.id}
              href={`/admin/games/${game.id}/edit`}
              className="flex items-center justify-between rounded-card border border-ink-800 bg-ink-900 p-4 hover:border-brand-600/60"
            >
              <span className="text-sm text-ink-100">Игра №{game.id}</span>
              <span className="text-xs text-ink-500">{formatDateTime(game.starts_at)}</span>
            </Link>
          ))}
        </div>
      </div>

      {/* Заявок на вступление и правок профиля здесь больше нет: и то, и
          другое разбирается в Telegram, кнопками под уведомлением бота
          (ARCHITECTURE.md, раздел 3.8). Держать вторую копию тех же двух
          очередей значило бы разводить два места, где «уже рассмотрено»
          выясняется только по нажатию. */}
      <PassList />
    </div>
  );
}
