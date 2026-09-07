"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Plus, PencilSimple, Trash } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { clientFetch, ApiError } from "@/lib/api";
import type { GameListItem, GameListOut } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";
import { LinkButton } from "@/components/ui/button";
import { ResultBadge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { SchedulePanel } from "@/components/admin/schedule/schedule-panel";

/** Три состояния одного раздела, а не три пункта меню: планирование, оценка и
 * архив -- это последовательные стадии жизни одной и той же игры. */
const TABS = [
  { id: "schedule", label: "Расписание" },
  { id: "pending", label: "Ждут оценки" },
  { id: "rated", label: "Оценённые" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function isTab(value: string | null): value is TabId {
  return TABS.some((tab) => tab.id === value);
}

export default function AdminGamesPage() {
  return (
    // useSearchParams требует границы Suspense: вкладка и открытый день живут в
    // URL, чтобы возврат из формы оценки не выбрасывал админа в начало раздела.
    <Suspense fallback={<h1 className="font-display text-2xl text-ink-50">Игры</h1>}>
      <GamesTabs />
    </Suspense>
  );
}

function GamesTabs() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const rawTab = params.get("tab");
  const tab: TabId = isTab(rawTab) ? rawTab : "schedule";
  const day = params.get("day");
  const rawSession = Number(params.get("session"));
  const sessionId = Number.isInteger(rawSession) && rawSession > 0 ? rawSession : null;

  const navigate = useCallback(
    (next: { tab?: TabId; day?: string | null; session?: number | null }) => {
      const search = new URLSearchParams();
      search.set("tab", next.tab ?? tab);
      if (next.day) search.set("day", next.day);
      if (next.session) search.set("session", String(next.session));
      router.replace(`${pathname}?${search.toString()}`, { scroll: false });
    },
    [pathname, router, tab]
  );

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl text-ink-50">Игры</h1>
        {/* «Добавить» заводит игру сразу с результатом, минуя запись в боте --
            так вносят исторические игры. К расписанию отношения не имеет. */}
        <LinkButton href="/mafia/admin/games/new" className="!px-4">
          <Plus size={16} />
          Добавить
        </LinkButton>
      </div>

      <nav className="mt-5 flex gap-1 overflow-x-auto border-b border-ink-800">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => navigate({ tab: item.id, day: null, session: null })}
            className={clsx(
              "-mb-px shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
              tab === item.id
                ? "border-brand-500 text-ink-50"
                : "border-transparent text-ink-400 hover:text-ink-100"
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="mt-6">
        {tab === "schedule" && (
          <SchedulePanel
            day={day}
            sessionId={sessionId}
            onOpenDay={(value) => navigate({ day: value })}
            onOpenSession={(id) => navigate({ day, session: id })}
            onBackToDays={() => navigate({ day: null, session: null })}
          />
        )}
        {tab === "pending" && <PendingReview />}
        {tab === "rated" && <RatedGames />}
      </div>
    </div>
  );
}

function PendingReview() {
  const [games, setGames] = useState<GameListItem[] | null>(null);
  const [toDrop, setToDrop] = useState<GameListItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    clientFetch<GameListItem[]>("/api/admin/games/pending-review")
      .then(setGames)
      .catch(() => setGames([]));
  }, []);

  useEffect(load, [load]);

  async function drop() {
    if (!toDrop) return;
    setBusy(true);
    setError(null);
    try {
      await clientFetch(`/api/admin/games/${toDrop.id}`, { method: "DELETE" });
      setToDrop(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось удалить");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="text-xs text-ink-500">
        Игры, проведение которых подтвердили в расписании. Оцените через карандаш или оставьте без
        оценки корзиной — запись просто исчезнет из этого списка.
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {games === null && <p className="text-sm text-ink-500">Загрузка…</p>}
        {games?.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-6 text-center text-sm text-ink-500">
            Пока нечего оценивать.
          </p>
        )}
        {games?.map((game) => (
          <GameRow key={game.id} game={game} onDelete={setToDrop} pending />
        ))}
      </div>

      <ConfirmDialog
        open={toDrop !== null}
        title={`Оставить игру №${toDrop?.id} без оценки?`}
        description="Игра исчезнет из списка ожидания вместе с составом, который в ней записан. Восстановить её можно будет только вручную."
        confirmLabel="Оставить без оценки"
        busy={busy}
        error={error}
        onConfirm={drop}
        onCancel={() => {
          setToDrop(null);
          setError(null);
        }}
      />
    </div>
  );
}

function RatedGames() {
  const [rated, setRated] = useState<GameListOut | null>(null);
  const [toDelete, setToDelete] = useState<GameListItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    clientFetch<GameListOut>("/api/admin/games?limit=50")
      .then(setRated)
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }, []);

  useEffect(load, [load]);

  async function remove() {
    if (!toDelete) return;
    setBusy(true);
    setError(null);
    try {
      await clientFetch(`/api/admin/games/${toDelete.id}`, { method: "DELETE" });
      setToDelete(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось удалить");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {loadError && <p className="text-sm text-brand-300">{loadError}</p>}
      <div className="flex flex-col gap-2">
        {rated?.items.map((game) => (
          <GameRow key={game.id} game={game} onDelete={setToDelete} />
        ))}
        {rated?.items.length === 0 && (
          <p className="rounded-card border border-ink-800 bg-ink-900 p-6 text-center text-sm text-ink-500">
            Пока нет оценённых игр.
          </p>
        )}
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        title={`Удалить игру №${toDelete?.id}?`}
        description="Игра и её результат удалятся безвозвратно, рейтинг всех участников будет пересчитан заново."
        confirmLabel="Удалить игру"
        busy={busy}
        error={error}
        onConfirm={remove}
        onCancel={() => {
          setToDelete(null);
          setError(null);
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
