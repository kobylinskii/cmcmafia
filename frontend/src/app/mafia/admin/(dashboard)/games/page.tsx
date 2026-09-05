"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus, PencilSimple, Trash } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import type { GameListItem, GameListOut } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";
import { LinkButton } from "@/components/ui/button";
import { ResultBadge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

export default function AdminGamesPage() {
  const [pending, setPending] = useState<GameListItem[]>([]);
  const [rated, setRated] = useState<GameListOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<{ game: GameListItem; pending: boolean } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function load() {
    clientFetch<GameListItem[]>("/api/admin/games/pending-review").then(setPending).catch(() => setPending([]));
    clientFetch<GameListOut>("/api/admin/games?limit=50")
      .then(setRated)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }

  useEffect(load, []);

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await clientFetch(`/api/admin/games/${toDelete.game.id}`, { method: "DELETE" });
      setToDelete(null);
      load();
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Не удалось удалить");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-ink-50">Игры</h1>
        <LinkButton href="/mafia/admin/games/new" className="!px-4">
          <Plus size={16} />
          Добавить
        </LinkButton>
      </div>

      {pending.length > 0 && (
        <div className="mt-6">
          <h2 className="text-sm font-medium text-ink-300">Ждут оценки</h2>
          <p className="mt-1 text-xs text-ink-500">
            Пришли из бота, время игры прошло. Оцените через карандаш или оставьте без оценки корзиной —
            запись просто исчезнет из этого списка.
          </p>
          <div className="mt-2 flex flex-col gap-2">
            {pending.map((g) => (
              <GameRow key={g.id} game={g} onDelete={(game) => setToDelete({ game, pending: true })} pending />
            ))}
          </div>
        </div>
      )}

      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}

      <div className="mt-6">
        <h2 className="text-sm font-medium text-ink-300">Оценённые игры</h2>
        <div className="mt-2 flex flex-col gap-2">
          {rated?.items.map((g) => (
            <GameRow key={g.id} game={g} onDelete={(game) => setToDelete({ game, pending: false })} />
          ))}
          {rated?.items.length === 0 && (
            <p className="rounded-card border border-ink-800 bg-ink-900 p-6 text-center text-sm text-ink-500">
              Пока нет оценённых игр.
            </p>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        title={
          toDelete?.pending
            ? `Оставить игру №${toDelete.game.id} без оценки?`
            : `Удалить игру №${toDelete?.game.id}?`
        }
        description={
          toDelete?.pending
            ? "Запись из бота исчезнет из списка ожидания вместе с составом, который в ней записан. Восстановить её можно будет только вручную."
            : "Игра и её результат удалятся безвозвратно, рейтинг всех участников будет пересчитан заново."
        }
        confirmLabel={toDelete?.pending ? "Оставить без оценки" : "Удалить игру"}
        busy={deleting}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => {
          setToDelete(null);
          setDeleteError(null);
        }}
      />
    </div>
  );
}

function GameRow({
  game,
  onDelete,
  pending = false,
}: {
  game: GameListItem;
  onDelete: (game: GameListItem) => void;
  pending?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-900 p-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-ink-100">Игра №{game.id}</span>
        <span className="text-ink-500">{formatDateTime(game.starts_at)}</span>
        <span className="text-ink-500">{GAME_TYPE_LABELS[game.game_type]}</span>
        <ResultBadge result={game.result} />
      </div>
      <div className="flex items-center gap-1">
        <Link
          href={`/mafia/admin/games/${game.id}/edit`}
          title="Оценить"
          className="rounded-lg p-2 text-ink-400 hover:bg-ink-850 hover:text-ink-50"
        >
          <PencilSimple size={16} />
        </Link>
        <button
          onClick={() => onDelete(game)}
          title={pending ? "Оставить без оценки" : "Удалить"}
          className="rounded-lg p-2 text-ink-400 hover:bg-brand-900/40 hover:text-brand-300"
        >
          <Trash size={16} />
        </button>
      </div>
    </div>
  );
}
