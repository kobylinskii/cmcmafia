"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import type { GameOut } from "@/types/api";
import { GameForm } from "@/components/admin/game-form";

export default function EditGamePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [game, setGame] = useState<(GameOut & { id: number }) | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    clientFetch<GameOut>(`/api/admin/games/${id}`)
      .then((g) => setGame({ ...g, id: g.id }))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }, [id]);

  return (
    <div>
      {/* Ссылка ведёт туда же, куда форма возвращает после сохранения:
          турнирную игру админ открывает из карточки турнира, а не из общего
          списка игр (турнирных там вообще нет). */}
      <Link
        href={game?.tournament ? `/mafia/admin/tournaments/${game.tournament.id}/edit` : "/mafia/admin/games"}
        className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100"
      >
        <ArrowLeft size={16} />
        {game?.tournament ? game.tournament.name : "Игры"}
      </Link>
      <h1 className="mt-3 font-display text-2xl text-ink-50">
        {game ? `Игра №${game.id}` : "Загрузка…"}
        {game?.stage && <span className="ml-3 text-base text-ink-400">{game.stage.name}</span>}
      </h1>
      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}
      {game && (
        <div className="mt-6">
          <GameForm game={game} />
        </div>
      )}
    </div>
  );
}
