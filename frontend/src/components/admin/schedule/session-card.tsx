"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, CheckCircle, Prohibit, Trash } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useConfirmable } from "@/lib/use-confirmable";
import { formatDateTime, fromClubDatetimeLocal, toDatetimeLocalValue } from "@/lib/format";
import { fieldDense as field, fieldLabel as label } from "@/lib/ui";
import type { RegistrationRole, ScheduleGameType, ScheduleSessionOut } from "@/types/api";
import { GAME_TYPE_LABELS, SCHEDULE_GAME_TYPES } from "@/types/api";

const ROSTER_ROLE_LABELS: Record<RegistrationRole, string> = {
  host: "Ведущий",
  judge: "Судья",
  player: "Игрок",
};

// Ведущий и двое судей сверх стола (registration_service.HOST_LIMIT/JUDGE_LIMIT).
const STAFF_SEATS = 3;

/** Статусы, из которых игру ещё можно подтвердить как проведённую -- те же,
 * что проверяет game_service.UNCONFIRMED_STATUSES на бэкенде. */
const UNCONFIRMED = new Set(["scheduled", "registration_closed"]);

/** Игра прошла, её собирались оценивать, но админ ещё не сказал, состоялась ли
 * она. Это единственное состояние, из которого сессия попадает в «Ждут
 * оценки»: наступление времени само по себе ничего о ней не говорит. */
function needsConfirmation(session: ScheduleSessionOut): boolean {
  return (
    session.needs_rating &&
    UNCONFIRMED.has(session.status) &&
    new Date(session.starts_at) <= new Date()
  );
}

/**
 * Карточка слота: то же, что было в боте, плюс флаг оценки.
 *
 * Уведомления записавшимся о переносе бот больше не шлёт: писать в Telegram
 * может только он, а планировщик теперь на сайте (см. ARCHITECTURE.md,
 * раздел 12). Поэтому о переносе предупреждает подпись под полем времени --
 * чтобы админ сам сообщил людям, а не думал, что это сделано за него.
 */
export function SessionCard({
  sessionId,
  locations,
  onBack,
  onChanged,
}: {
  sessionId: number;
  locations: string[];
  onBack: () => void;
  onChanged: () => void;
}) {
  const [session, setSession] = useState<ScheduleSessionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const del = useConfirmable<"delete" | "not-held">(async () => {
    await clientFetch(`/api/admin/schedule/sessions/${sessionId}`, { method: "DELETE" });
    onChanged();
    onBack();
  }, "Не удалось удалить игру");

  // Неконтролируемое поле: <input type="datetime-local"> отдаёт "" для любого
  // не до конца заполненного значения, и при controlled value набранная дата
  // стиралась бы на каждом промежуточном onChange (см. game-form.tsx).
  const startsAtRef = useRef<HTMLInputElement>(null);
  const [location, setLocation] = useState("");
  const [gameType, setGameType] = useState<ScheduleGameType>("funky");
  const [needsRating, setNeedsRating] = useState(true);

  function apply(next: ScheduleSessionOut) {
    setSession(next);
    setLocation(next.location ?? "");
    setGameType(next.game_type === "tournament" ? "funky" : next.game_type);
    setNeedsRating(next.needs_rating);
    if (startsAtRef.current) startsAtRef.current.value = toDatetimeLocalValue(next.starts_at);
  }

  useEffect(() => {
    clientFetch<ScheduleSessionOut>(`/api/admin/schedule/sessions/${sessionId}`)
      .then(apply)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить игру"));
  }, [sessionId]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const next = await clientFetch<ScheduleSessionOut>(`/api/admin/schedule/sessions/${sessionId}`, {
        method: "PUT",
        body: JSON.stringify({
          starts_at: fromClubDatetimeLocal(startsAtRef.current!.value),
          location: location.trim(),
          game_type: gameType,
          needs_rating: needsRating,
        }),
      });
      apply(next);
      setSaved("Сохранено");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  async function markPlayed() {
    setSaving(true);
    setError(null);
    try {
      const next = await clientFetch<ScheduleSessionOut>(
        `/api/admin/schedule/sessions/${sessionId}/played`,
        { method: "POST" }
      );
      apply(next);
      setSaved("Игра отмечена проведённой — она ушла во вкладку «Ждут оценки»");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось отметить игру");
    } finally {
      setSaving(false);
    }
  }

  if (error && !session) return <p className="text-sm text-brand-300">{error}</p>;
  if (!session) return <p className="text-sm text-ink-500">Загрузка…</p>;

  const registered = session.hosts + session.judges + session.players;
  const awaiting = needsConfirmation(session);

  return (
    <div>
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100"
      >
        <ArrowLeft size={16} />
        Назад
      </button>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h2 className="font-display text-xl text-ink-50">Игра №{session.id}</h2>
        <Badge tone="outline">{GAME_TYPE_LABELS[session.game_type]}</Badge>
        {!session.needs_rating && <Badge tone="neutral">Без оценки</Badge>}
        {session.status === "played" && <Badge tone="brand">Ждёт оценки</Badge>}
      </div>
      <p className="mt-1 text-sm text-ink-400">
        {formatDateTime(session.starts_at)} · {session.location || "место не указано"} ·{" "}
        {registered} из {session.max_players + STAFF_SEATS} мест
        {session.reserves > 0 && ` · резерв ${session.reserves}`}
      </p>

      {awaiting && (
        <div className="mt-5 rounded-card border border-brand-800 bg-brand-900/20 p-4">
          <p className="text-sm text-ink-100">Игра прошла. Она состоялась?</p>
          <p className="mt-1 text-xs text-ink-400">
            Подтверждённая уходит во вкладку «Ждут оценки». «Не состоялась» — это удаление вместе
            со всеми записями: в статистику и рейтинг такая игра не попадёт.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" className="!px-4 !py-2" disabled={saving} onClick={markPlayed}>
              <CheckCircle size={16} />
              Игра проведена
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="!px-4 !py-2"
              disabled={saving}
              onClick={() => del.ask("not-held")}
            >
              <Prohibit size={16} />
              Не состоялась
            </Button>
          </div>
        </div>
      )}

      <form onSubmit={save} className="mt-6 rounded-card border border-ink-800 bg-ink-900 p-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <label className={label}>
            Дата и время
            {/* defaultValue, а не присваивание через ref: форма монтируется
                только после загрузки слота, и к моменту первого apply() ref
                ещё пуст -- поле оставалось незаполненным. Последующие apply
                (после сохранения) ref уже находят и обновляют значение. */}
            <input
              ref={startsAtRef}
              type="datetime-local"
              className={field}
              defaultValue={toDatetimeLocalValue(session.starts_at)}
              required
            />
            <span className="font-normal text-ink-500">
              О переносе записавшихся предупредите сами: бот об изменениях не пишет.
            </span>
          </label>
          <label className={label}>
            Место
            <input
              className={field}
              list="session-locations"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              maxLength={200}
              required
            />
            <datalist id="session-locations">
              {locations.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
          </label>
          <label className={label}>
            Формат
            <select
              className={field}
              value={gameType}
              onChange={(e) => setGameType(e.target.value as ScheduleGameType)}
            >
              {SCHEDULE_GAME_TYPES.map((value) => (
                <option key={value} value={value}>
                  {GAME_TYPE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="mt-4 flex cursor-pointer items-start gap-2.5 text-sm text-ink-200">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-brand-600"
            checked={needsRating}
            onChange={(e) => setNeedsRating(e.target.checked)}
          />
          <span>
            Игра будет оцениваться
            <span className="mt-0.5 block text-xs font-normal text-ink-500">
              Снять флаг можно, пока игра не оценена. С уже проведённой игры он снимет и
              подтверждение — из «Ждут оценки» она уйдёт.
            </span>
          </span>
        </label>

        {error && (
          <p role="alert" className="mt-4 rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200">
            {error}
          </p>
        )}
        {saved && !error && <p className="mt-4 text-sm text-ink-300">{saved}</p>}

        <div className="mt-5 flex flex-wrap gap-2">
          <Button type="submit" className="!px-5 !py-2.5" disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            className="!px-5 !py-2.5"
            disabled={saving}
            onClick={() => del.ask("delete")}
          >
            <Trash size={16} />
            Удалить игру
          </Button>
        </div>
      </form>

      <div className="mt-6 rounded-card border border-ink-800 bg-ink-900 p-5">
        <h3 className="text-sm font-medium text-ink-300">Записались в боте</h3>
        {session.roster.registrations.length === 0 && session.roster.reserves.length === 0 ? (
          <p className="mt-2 text-sm text-ink-500">Пока никого.</p>
        ) : (
          <>
            <ul className="mt-2.5 flex flex-wrap gap-2">
              {session.roster.registrations.map((member, index) => (
                <li
                  key={`${member.nickname}-${index}`}
                  className="rounded-pill border border-ink-700 bg-ink-850 px-3 py-1 text-xs text-ink-200"
                >
                  {member.nickname}
                  <span className="ml-1.5 text-ink-500">· {ROSTER_ROLE_LABELS[member.role]}</span>
                </li>
              ))}
            </ul>
            {session.roster.reserves.length > 0 && (
              <>
                <h3 className="mt-4 text-sm font-medium text-ink-300">Резерв</h3>
                <ul className="mt-2.5 flex flex-wrap gap-2">
                  {session.roster.reserves.map((member, index) => (
                    <li
                      key={`${member.nickname}-${index}`}
                      className="rounded-pill border border-ink-700 bg-ink-850 px-3 py-1 text-xs text-ink-200"
                    >
                      {member.nickname}
                      <span className="ml-1.5 text-ink-500">· №{index + 1}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>

      <ConfirmDialog
        open={del.target !== null}
        title={
          del.target === "not-held"
            ? `Игра №${session.id} не состоялась?`
            : `Удалить игру №${session.id}?`
        }
        description={
          `${formatDateTime(session.starts_at)}. Записано человек: ${registered}` +
          (session.reserves > 0 ? ` и ещё ${session.reserves} в резерве` : "") +
          ". Их записи исчезнут вместе с игрой, в статистику и рейтинг она не попадёт."
        }
        confirmLabel={del.target === "not-held" ? "Да, не состоялась" : "Удалить игру"}
        busy={del.busy}
        error={del.error}
        onConfirm={del.run}
        onCancel={del.close}
      />
    </div>
  );
}
