"use client";

import { useEffect, useState } from "react";
import { Check, UserFocus, X } from "@phosphor-icons/react/dist/ssr";
import { ApiError, clientFetch } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AFFILIATION_LABELS,
  ROLE_LABELS,
  type PendingPlayerOut,
} from "@/types/api";

/** Заявки на вступление, пришедшие из бота.
 *
 * Регистрация в боте открыта кому угодно, поэтому новый человек не попадает
 * на публичную часть сайта, пока его тут не подтвердят. Записываться на игры
 * он при этом может сразу -- отсюда и место блока: «Обзор», а не отдельная
 * страница, куда никто не ходит.
 */
export function PendingPlayers() {
  const [items, setItems] = useState<PendingPlayerOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  function load() {
    clientFetch<PendingPlayerOut[]>("/api/admin/players/pending")
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить заявки"));
  }

  useEffect(load, []);

  async function decide(player: PendingPlayerOut, decision: "confirm" | "reject") {
    setBusyId(player.id);
    setError(null);
    try {
      await clientFetch(`/api/admin/players/${player.id}/${decision}`, {
        method: "POST",
        body: decision === "reject" ? JSON.stringify({ reason: reason.trim() }) : undefined,
      });
      setRejecting(null);
      setReason("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить решение");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="mt-10">
      <h2 className="flex items-center gap-2 font-display text-lg text-ink-50">
        <UserFocus size={18} className="text-brand-400" />
        Ожидают подтверждения
        {items && items.length > 0 && <Badge tone="brand">{items.length}</Badge>}
      </h2>
      <p className="mt-1 text-sm text-ink-400">
        Игроки, зарегистрировавшиеся в боте. До подтверждения их нет ни в рейтинге, ни в списке
        игроков на сайте — но записываться на игры они уже могут.
      </p>

      {error && <p className="mt-3 text-sm text-brand-300">{error}</p>}

      <div className="mt-4 flex flex-col gap-3">
        {items === null && <p className="text-sm text-ink-500">Загрузка…</p>}
        {items?.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-5 text-sm text-ink-500">
            Новых заявок нет.
          </p>
        )}

        {items?.map((player) => (
          <article key={player.id} className="rounded-card border border-ink-800 bg-ink-900 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink-50">
                  {player.nickname}
                  {player.full_name && <span className="text-ink-400"> — {player.full_name}</span>}
                </p>
                <p className="mt-1 text-xs text-ink-500">
                  Заявка от {formatDateTime(player.created_at)}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  className="!px-4 !py-2"
                  disabled={busyId === player.id}
                  onClick={() => decide(player, "confirm")}
                >
                  <Check size={16} />
                  Подтвердить
                </Button>
                <Button
                  variant="secondary"
                  className="!px-4 !py-2"
                  disabled={busyId === player.id}
                  onClick={() => {
                    setRejecting(rejecting === player.id ? null : player.id);
                    setReason("");
                  }}
                >
                  <X size={16} />
                  Отклонить
                </Button>
              </div>
            </div>

            <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <Row label="Обращение" value={player.salutation} />
              <Row
                label="Статус по пропуску"
                value={player.affiliation ? AFFILIATION_LABELS[player.affiliation] : null}
              />
              <Row label="Телефон" value={player.phone} />
              <Row
                label="Telegram"
                value={player.telegram_username ? `@${player.telegram_username}` : player.telegram_id}
              />
              <Row
                label="Роли"
                value={
                  [player.can_play && "игрок", player.can_staff && "ведущий/судья"]
                    .filter(Boolean)
                    .join(", ") || null
                }
              />
              <Row label="Возраст" value={player.age} />
              <Row
                label="Любимая роль"
                value={player.favorite_role ? ROLE_LABELS[player.favorite_role] : null}
              />
              <Row label="Опыт" value={player.experience} />
              <Row label="О себе" value={player.bio} />
            </dl>

            {rejecting === player.id && (
              <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950 p-4">
                <label className="flex flex-col gap-1.5 text-xs text-ink-400">
                  Причина отклонения — её увидит игрок в боте
                  <textarea
                    autoFocus
                    rows={2}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Например: ФИО не совпадает с указанным в заявке на пропуск"
                    className="rounded-lg border border-ink-700 bg-ink-950 px-3.5 py-2.5 text-sm text-ink-50 focus:border-brand-500 focus:outline-none"
                  />
                </label>
                <div className="mt-3 flex justify-end gap-2">
                  <Button variant="ghost" className="!px-4 !py-2" onClick={() => setRejecting(null)}>
                    Отмена
                  </Button>
                  <Button
                    className="!px-4 !py-2"
                    disabled={!reason.trim() || busyId === player.id}
                    onClick={() => decide(player, "reject")}
                  >
                    Отклонить заявку
                  </Button>
                </div>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-ink-500">{label}:</dt>
      <dd className="min-w-0 break-words text-ink-200">{value}</dd>
    </div>
  );
}
