"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus, PencilSimple, Trash, MapPin } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import type { TournamentAdminOut } from "@/types/api";
import { LinkButton } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { withCount } from "@/lib/format";

export default function AdminTournamentsPage() {
  const [tournaments, setTournaments] = useState<TournamentAdminOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<TournamentAdminOut | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function load() {
    clientFetch<TournamentAdminOut[]>("/api/admin/tournaments")
      .then(setTournaments)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }

  useEffect(load, []);

  async function confirmDelete() {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await clientFetch(`/api/admin/tournaments/${toDelete.id}`, { method: "DELETE" });
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
        <h1 className="font-display text-2xl text-ink-50">Турниры</h1>
        <LinkButton href="/mafia/admin/tournaments/new" className="!px-4">
          <Plus size={16} />
          Добавить
        </LinkButton>
      </div>

      <p className="mt-2 max-w-2xl text-sm text-ink-400">
        Без турнира турнирный результат внести не получится.
      </p>

      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}

      {tournaments === null && <p className="mt-6 text-sm text-ink-500">Загрузка…</p>}

      {tournaments?.length === 0 && (
        <div className="mt-8 border-l-2 border-brand-700 py-4 pl-6">
          <p className="font-display text-lg text-ink-100">Турниров пока нет</p>
          <p className="mt-2 max-w-lg text-sm leading-relaxed text-ink-400">
            Заведите первый — потом его можно будет выбрать в форме игры.
          </p>
        </div>
      )}

      {tournaments && tournaments.length > 0 && (
        <ul className="mt-6 divide-y divide-ink-800 border-y border-ink-800">
          {tournaments.map((tournament) => (
            <li
              key={tournament.id}
              className="flex flex-wrap items-center justify-between gap-3 py-4"
            >
              <div className="min-w-0">
                <p className="text-base text-ink-50">{tournament.name}</p>
                <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-500">
                  <span className="font-mono">{tournament.slug}</span>
                  {tournament.location && (
                    <span className="inline-flex items-center gap-1.5">
                      <MapPin size={14} />
                      {tournament.location}
                    </span>
                  )}
                  <span className="font-mono text-ink-400">
                    {withCount(tournament.games_count, ["игра", "игры", "игр"])}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Link
                  href={`/mafia/admin/tournaments/${tournament.id}/edit`}
                  title="Редактировать"
                  className="rounded-lg p-2 text-ink-400 hover:bg-ink-850 hover:text-ink-50"
                >
                  <PencilSimple size={17} />
                </Link>
                <button
                  onClick={() => setToDelete(tournament)}
                  title="Удалить"
                  className="rounded-lg p-2 text-ink-400 hover:bg-brand-900/40 hover:text-brand-300"
                >
                  <Trash size={17} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title={`Удалить турнир «${toDelete?.name}»?`}
        description={
          toDelete && toDelete.games_count > 0 ? (
            <>
              В турнире {withCount(toDelete.games_count, ["сыгранная партия", "сыгранные партии", "сыгранных партий"])}. Пока они к нему привязаны,
              удалить его нельзя — сначала перенесите игры в другой турнир.
            </>
          ) : (
            "Турнир будет удалён безвозвратно."
          )
        }
        confirmLabel="Удалить турнир"
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
