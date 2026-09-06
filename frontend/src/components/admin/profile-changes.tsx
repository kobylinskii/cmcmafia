"use client";

import { useEffect, useState } from "react";
import { Check, PencilSimple, X } from "@phosphor-icons/react/dist/ssr";
import { ApiError, clientFetch } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { ProfileChangeOut } from "@/types/api";

/** Правки профилей, отправленные игроками из бота.
 *
 * Профиль игрока -- это ФИО в списке на пропуск и ник в рейтинге и составах,
 * то есть то, по чему человека узнают в клубе. Подтверждённый участник не
 * переписывает их молча: до решения здесь в профиле действует прежнее
 * значение, а игрок видит в боте пометку «на проверке».
 *
 * Место то же, что и у заявок на вступление, и по той же причине: это
 * очередь, в которую надо заглядывать, а не страница, куда специально ходят.
 */
export function ProfileChanges() {
  const [items, setItems] = useState<ProfileChangeOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  function load() {
    clientFetch<ProfileChangeOut[]>("/api/admin/players/profile-changes")
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить правки"));
  }

  useEffect(load, []);

  async function decide(change: ProfileChangeOut, decision: "apply" | "reject") {
    setBusyId(change.id);
    setError(null);
    try {
      await clientFetch(`/api/admin/players/profile-changes/${change.id}/${decision}`, {
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
        <PencilSimple size={18} className="text-brand-400" />
        Правки профилей
        {items && items.length > 0 && <Badge tone="brand">{items.length}</Badge>}
      </h2>
      <p className="mt-1 text-sm text-ink-400">
        Игроки поправили свои данные в боте. До подтверждения в профиле действует прежнее
        значение — на сайте и в списках на пропуск ничего не меняется.
      </p>

      {error && <p className="mt-3 text-sm text-brand-300">{error}</p>}

      <div className="mt-4 flex flex-col gap-3">
        {items === null && <p className="text-sm text-ink-500">Загрузка…</p>}
        {items?.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-5 text-sm text-ink-500">
            Новых правок нет.
          </p>
        )}

        {items?.map((change) => (
          <article key={change.id} className="rounded-card border border-ink-800 bg-ink-900 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink-50">
                  {change.player_nickname}
                  <span className="text-ink-400"> — {change.field_label}</span>
                </p>
                <p className="mt-1 text-xs text-ink-500">
                  Отправлено {formatDateTime(change.created_at)}
                  {change.telegram_username && ` · @${change.telegram_username}`}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  className="!px-4 !py-2"
                  disabled={busyId === change.id}
                  onClick={() => decide(change, "apply")}
                >
                  <Check size={16} />
                  Применить
                </Button>
                <Button
                  variant="secondary"
                  className="!px-4 !py-2"
                  disabled={busyId === change.id}
                  onClick={() => {
                    setRejecting(rejecting === change.id ? null : change.id);
                    setReason("");
                  }}
                >
                  <X size={16} />
                  Отклонить
                </Button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Value label="Сейчас" value={change.current_value} />
              <Value label="Станет" value={change.new_value} highlighted />
            </div>

            {rejecting === change.id && (
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
                    disabled={!reason.trim() || busyId === change.id}
                    onClick={() => decide(change, "reject")}
                  >
                    Отклонить правку
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

function Value({
  label,
  value,
  highlighted = false,
}: {
  label: string;
  value: string | null;
  highlighted?: boolean;
}) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-950 p-3">
      <p className="text-xs text-ink-500">{label}</p>
      <p
        className={`mt-1 whitespace-pre-wrap break-words text-sm ${
          highlighted ? "text-ink-50" : "text-ink-300"
        }`}
      >
        {value ?? <span className="text-ink-600">— пусто</span>}
      </p>
    </div>
  );
}
