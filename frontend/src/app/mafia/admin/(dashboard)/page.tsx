"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ListChecks, UsersThree, Warning } from "@phosphor-icons/react/dist/ssr";
import { clientFetch } from "@/lib/api";
import type { GameListItem } from "@/types/api";
import { formatDateTime } from "@/lib/format";
import { PendingPlayers } from "@/components/admin/pending-players";
import { ProfileChanges } from "@/components/admin/profile-changes";
import { PassList } from "@/components/admin/pass-list";

export default function AdminOverviewPage() {
  const [pending, setPending] = useState<GameListItem[] | null>(null);

  useEffect(() => {
    clientFetch<GameListItem[]>("/api/admin/games/pending-review")
      .then(setPending)
      .catch(() => setPending([]));
  }, []);

  return (
    <div className="max-w-3xl">
      <h1 className="font-display text-2xl text-ink-50">Обзор</h1>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Link
          href="/mafia/admin/games/new"
          className="flex items-center gap-3 rounded-card border border-ink-800 bg-ink-900 p-5 hover:border-brand-600/60"
        >
          <ListChecks size={22} className="text-brand-400" />
          <div>
            <p className="font-medium text-ink-50">Добавить игру</p>
            <p className="text-xs text-ink-400">Новый результат по шаблону</p>
          </div>
        </Link>
        <Link
          href="/mafia/admin/players/new"
          className="flex items-center gap-3 rounded-card border border-ink-800 bg-ink-900 p-5 hover:border-brand-600/60"
        >
          <UsersThree size={22} className="text-brand-400" />
          <div>
            <p className="font-medium text-ink-50">Добавить игрока</p>
            <p className="text-xs text-ink-400">Профиль нового участника</p>
          </div>
        </Link>
      </div>

      <div className="mt-10">
        <h2 className="flex items-center gap-2 font-display text-lg text-ink-50">
          <Warning size={18} className="text-brand-400" />
          Ждут оценки
        </h2>
        <p className="mt-1 text-sm text-ink-400">
          Сессии из бота, время которых уже прошло, но результат ещё не внесён.
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
              href={`/mafia/admin/games/${game.id}/edit`}
              className="flex items-center justify-between rounded-card border border-ink-800 bg-ink-900 p-4 hover:border-brand-600/60"
            >
              <span className="text-sm text-ink-100">Игра №{game.id}</span>
              <span className="text-xs text-ink-500">{formatDateTime(game.starts_at)}</span>
            </Link>
          ))}
        </div>
      </div>

      <PendingPlayers />
      <ProfileChanges />

      <PassList />
    </div>
  );
}
