"use client";

import { useState } from "react";
import { Check, UserFocus, X } from "@phosphor-icons/react/dist/ssr";
import { ApiError, clientFetch } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RejectReasonBox } from "@/components/admin/reject-reason-box";
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
  const { data: items, error, reload } = useResource<PendingPlayerOut[]>(
    "/api/admin/players/pending",
    "Не удалось загрузить заявки"
  );
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [decideError, setDecideError] = useState<string | null>(null);

  async function decide(player: PendingPlayerOut, decision: "confirm" | "reject") {
    setBusyId(player.id);
    setDecideError(null);
    try {
      await clientFetch(`/api/admin/players/${player.id}/${decision}`, {
        method: "POST",
        body: decision === "reject" ? JSON.stringify({ reason: reason.trim() }) : undefined,
      });
      setRejecting(null);
      setReason("");
      reload();
    } catch (err) {
      setDecideError(err instanceof ApiError ? err.message : "Не удалось сохранить решение");
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

      {(error || decideError) && (
        <p className="mt-3 text-sm text-brand-300">{error || decideError}</p>
      )}

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
              <RejectReasonBox
                reason={reason}
                onReason={setReason}
                onCancel={() => setRejecting(null)}
                onConfirm={() => decide(player, "reject")}
                confirmLabel="Отклонить заявку"
                busy={busyId === player.id}
              />
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
