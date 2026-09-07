"use client";

import Link from "next/link";
import { useState } from "react";
import { Plus, PencilSimple, Trash, Key } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { useConfirmable } from "@/lib/use-confirmable";
import type { PlayerAdminOut } from "@/types/api";
import { Button, LinkButton } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

export default function AdminPlayersPage() {
  const { data: players, error, reload } = useResource<PlayerAdminOut[]>("/api/admin/players");
  const [grantFor, setGrantFor] = useState<PlayerAdminOut | null>(null);

  const del = useConfirmable<PlayerAdminOut>(async (player) => {
    await clientFetch(`/api/admin/players/${player.id}`, { method: "DELETE" });
    reload();
  }, "Не удалось удалить");

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-ink-50">Игроки</h1>
        <LinkButton href="/mafia/admin/players/new" className="!px-4">
          <Plus size={16} />
          Добавить
        </LinkButton>
      </div>

      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}

      <div className="mt-6 overflow-x-auto rounded-card border border-ink-800">
        <table className="w-full min-w-[720px] border-collapse">
          <thead>
            <tr className="border-b border-ink-800 bg-ink-900 text-left text-xs font-medium text-ink-400">
              <th className="px-4 py-3">Ник</th>
              <th className="px-4 py-3">Slug</th>
              <th className="px-4 py-3">Статус</th>
              <th className="px-4 py-3">Telegram</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800">
            {players?.map((p) => (
              <tr key={p.id} className="odd:bg-ink-900/40">
                <td className="px-4 py-3 text-sm text-ink-50">{p.nickname}</td>
                <td className="px-4 py-3 font-mono text-sm text-ink-400">{p.slug}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    {!p.is_active && <Badge tone="outline">Скрыт</Badge>}
                    {p.confirmation_status !== "confirmed" && (
                      <Badge tone="outline">
                        {p.confirmation_status === "pending" ? "На проверке" : "Отклонён"}
                      </Badge>
                    )}
                    {p.is_bot_admin && <Badge tone="outline">Бот-админ</Badge>}
                    {p.is_site_admin && <Badge tone="brand">Сайт-админ</Badge>}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-ink-400">
                  {p.telegram_username ? `@${p.telegram_username}` : p.telegram_id ?? "—"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      title="Выдать доступ на сайт"
                      onClick={() => setGrantFor(p)}
                      className="rounded-lg p-2 text-ink-400 hover:bg-ink-850 hover:text-ink-50"
                    >
                      <Key size={16} />
                    </button>
                    <Link
                      href={`/mafia/admin/players/${p.id}/edit`}
                      className="rounded-lg p-2 text-ink-400 hover:bg-ink-850 hover:text-ink-50"
                    >
                      <PencilSimple size={16} />
                    </Link>
                    <button
                      onClick={() => del.ask(p)}
                      className="rounded-lg p-2 text-ink-400 hover:bg-brand-900/40 hover:text-brand-300"
                    >
                      <Trash size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {players?.length === 0 && <p className="p-8 text-center text-sm text-ink-500">Пока нет ни одного игрока.</p>}
      </div>

      {grantFor && <GrantAccessModal player={grantFor} onClose={() => setGrantFor(null)} />}

      <ConfirmDialog
        open={del.target !== null}
        title={`Удалить игрока «${del.target?.nickname}»?`}
        description={
          <>
            Если за игроком числятся сыгранные партии, он будет скрыт с сайта, но останется
            в составах и в истории рейтинга. Если игр нет — запись удалится полностью.
          </>
        }
        confirmLabel="Удалить игрока"
        busy={del.busy}
        error={del.error}
        onConfirm={del.run}
        onCancel={del.close}
      />
    </div>
  );
}

function GrantAccessModal({ player, onClose }: { player: PlayerAdminOut; onClose: () => void }) {
  const [username, setUsername] = useState(player.site_username ?? player.slug);
  const [result, setResult] = useState<{ site_username: string; temp_password: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleGrant() {
    setLoading(true);
    setError(null);
    try {
      const res = await clientFetch<{ site_username: string; temp_password: string }>(
        `/api/admin/players/${player.id}/site-access?username=${encodeURIComponent(username)}`,
        { method: "POST" }
      );
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось выдать доступ");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-sm rounded-card border border-ink-700 bg-ink-900 p-6">
        <h2 className="font-display text-lg text-ink-50">Доступ на сайт для {player.nickname}</h2>

        {!result ? (
          <>
            <label className="mt-4 flex flex-col gap-1.5 text-xs text-ink-400">
              Логин
              <input
                className="rounded-lg border border-ink-700 bg-ink-950 px-3.5 py-2.5 text-sm text-ink-50 focus:border-brand-500 focus:outline-none"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            {error && <p className="mt-3 text-sm text-brand-300">{error}</p>}
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                Отмена
              </Button>
              <Button onClick={handleGrant} disabled={loading}>
                {loading ? "Выдаём…" : "Выдать"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-4 text-sm text-ink-300">
              Логин: <span className="font-mono text-ink-50">{result.site_username}</span>
            </p>
            <p className="mt-1 text-sm text-ink-300">
              Временный пароль: <span className="font-mono text-ink-50">{result.temp_password}</span>
            </p>
            <p className="mt-3 text-xs text-ink-500">
              Передайте эти данные игроку лично — здесь пароль больше не покажется.
            </p>
            <div className="mt-5 flex justify-end">
              <Button onClick={onClose}>Готово</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
