"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CaretDown, CaretUp, Flag, PencilSimple, Plus, Trash } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useResource } from "@/lib/use-resource";
import { useConfirmable } from "@/lib/use-confirmable";
import { field } from "@/lib/ui";
import { formatDash, formatDateTime } from "@/lib/format";
import type { TournamentStageGameOut, TournamentStageOut, TournamentStandingOut } from "@/types/api";

/**
 * Игры турнира: слоты добавляются заранее (по числу игр), а их содержимое
 * (состав, результат) вносится позже отдельным шагом через общую форму игры.
 * Этапы (сетка по олимпийской системе) нужны только если участников больше
 * 10 -- обычный турнир из ≤10 игроков просто добавляет N игр без этапа.
 */
export function TournamentStagesManager({ tournamentId }: { tournamentId: number }) {
  return (
    <div className="flex flex-col gap-10">
      <FlatGamesPanel tournamentId={tournamentId} />
      <StagesPanel tournamentId={tournamentId} />
    </div>
  );
}

/** Список игровых слотов -- общий рендер и для игр турнира без этапа, и для
 * игр внутри конкретного этапа. Оценка и удаление слота идут через ту же
 * общую ручку /admin/games/{id}, что и для игр бота. */
function GameSlotList({
  games,
  onChanged,
}: {
  games: TournamentStageGameOut[];
  onChanged: () => void;
}) {
  // Номер игры в списке, а не её id: админ видит «Игра 1..N» внутри этапа, а
  // не сквозной идентификатор из базы, который ни о чём ему не говорит и
  // прыгает через десятки при удалении слотов. Ключ, ссылки и удаление
  // по-прежнему идут по настоящему id.
  const del = useConfirmable<{ game: TournamentStageGameOut; number: number }>(async ({ game }) => {
    await clientFetch(`/api/admin/games/${game.id}`, { method: "DELETE" });
    onChanged();
  });

  if (games.length === 0) {
    return <p className="text-sm text-ink-500">Игр пока нет.</p>;
  }

  return (
    <>
      {/* Сетка, а не список в одну колонку: слотов у этапа бывает больше
          десяти, и каждый занимал целую строку почти пустой ширины. Число
          колонок задаёт ширина самого блока, а не окна -- блок стоит в
          колонке рядом с панелью настроек. */}
      {/* @container на обёртке, а не на самой сетке: контейнерный запрос
          отвечает за ПОТОМКОВ элемента, так что @md: на том же узле, где
          объявлен @container, не срабатывает никогда. */}
      <div className="@container">
      <ul className="grid grid-cols-1 gap-2 @md:grid-cols-2 @3xl:grid-cols-3">
        {games.map((game, index) => (
          <li
            key={game.id}
            className="flex items-center justify-between gap-2 rounded-lg border border-ink-800 bg-ink-850 px-3.5 py-2.5"
          >
            <div className="flex min-w-0 flex-col gap-0.5 text-sm">
              <span className="flex items-center gap-2">
                <span className="text-ink-100">Игра {index + 1}</span>
                {game.status === "rated" ? (
                  <span className="rounded-pill bg-emerald-900/40 px-2 py-0.5 text-[11px] text-emerald-300">
                    Оценена
                  </span>
                ) : (
                  <span className="rounded-pill bg-ink-800 px-2 py-0.5 text-[11px] text-ink-400">
                    Ждёт оценки
                  </span>
                )}
              </span>
              <span className="truncate text-xs text-ink-500">{formatDateTime(game.starts_at)}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Link
                href={`/mafia/admin/games/${game.id}/edit`}
                title={game.status === "rated" ? "Изменить" : "Оценить"}
                className="rounded-lg p-2 text-ink-400 hover:bg-ink-800 hover:text-ink-50"
              >
                <PencilSimple size={16} />
              </Link>
              <button
                onClick={() => del.ask({ game, number: index + 1 })}
                title="Удалить"
                className="rounded-lg p-2 text-ink-400 hover:bg-brand-900/40 hover:text-brand-300"
              >
                <Trash size={16} />
              </button>
            </div>
          </li>
        ))}
      </ul>
      </div>

      <ConfirmDialog
        open={del.target !== null}
        title={del.target ? `Удалить игру ${del.target.number}?` : ""}
        description={
          del.target?.game.status === "rated"
            ? "Игра уже оценена — результат удалится безвозвратно, рейтинг всех участников будет пересчитан заново."
            : "Пустой слот будет удалён безвозвратно."
        }
        confirmLabel="Удалить"
        busy={del.busy}
        error={del.error}
        onConfirm={del.run}
        onCancel={del.close}
      />
    </>
  );
}

/** Кнопка + поле "сколько слотов добавить" -- общая форма и для турнира без
 * этапа, и для конкретного этапа (см. addUrl). */
function AddGamesForm({ addUrl, onAdded }: { addUrl: string; onAdded: () => void }) {
  const [count, setCount] = useState("1");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAdd() {
    const n = Number(count);
    if (!Number.isInteger(n) || n < 1) return;
    setAdding(true);
    setError(null);
    try {
      await clientFetch(addUrl, { method: "POST", body: JSON.stringify({ count: n }) });
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось добавить");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-400">
        Сколько игр добавить
        <input
          className={`${field} w-28 no-spinner`}
          type="number"
          min={1}
          max={64}
          value={count}
          onChange={(e) => setCount(e.target.value)}
        />
      </label>
      <Button type="button" variant="secondary" onClick={handleAdd} disabled={adding} className="!px-4">
        <Plus size={16} />
        {adding ? "Добавляем…" : "Добавить игры"}
      </Button>
      {error && <p className="text-sm text-brand-300">{error}</p>}
    </div>
  );
}

/** Игры турнира без этапа -- для простого турнира (≤10 участников), которому
 * никакой сетки не нужно, просто играется серия из N игр. */
function FlatGamesPanel({ tournamentId }: { tournamentId: number }) {
  const { data: games, error, reload } = useResource<TournamentStageGameOut[]>(
    `/api/admin/tournaments/${tournamentId}/games`,
    "Не удалось загрузить игры"
  );

  return (
    <div className="rounded-card border border-ink-800 bg-ink-900/60 p-5">
      <h2 className="font-display text-lg text-ink-50">Игры турнира</h2>
      <p className="mt-1 max-w-xl text-sm text-ink-400">
        Для турнира без сетки (≤10 участников) — просто добавьте нужное число игр и оцените
        каждую по мере проведения. Если участников больше 10, вместо этого заведите этапы ниже.
      </p>

      {error && <p className="mt-3 text-sm text-brand-300">{error}</p>}

      <div className="mt-4">
        <AddGamesForm addUrl={`/api/admin/tournaments/${tournamentId}/games`} onAdded={reload} />
      </div>

      <div className="mt-4">
        {games === null ? (
          <p className="text-sm text-ink-500">Загрузка…</p>
        ) : (
          <GameSlotList games={games} onChanged={reload} />
        )}
      </div>
    </div>
  );
}

function StagesPanel({ tournamentId }: { tournamentId: number }) {
  const { data: stages, error, reload } = useResource<TournamentStageOut[]>(
    `/api/admin/tournaments/${tournamentId}/stages`,
    "Не удалось загрузить этапы"
  );
  const [newName, setNewName] = useState("");
  const [newGamesCount, setNewGamesCount] = useState("1");
  const [newIsFinal, setNewIsFinal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [openStageId, setOpenStageId] = useState<number | null>(null);

  const del = useConfirmable<TournamentStageOut>(async (stage) => {
    await clientFetch(`/api/admin/tournaments/${tournamentId}/stages/${stage.id}`, { method: "DELETE" });
    reload();
  }, "Не удалось удалить этап");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const gamesCount = Number(newGamesCount);
    if (!newName.trim() || !Number.isInteger(gamesCount) || gamesCount < 1) return;
    setCreating(true);
    setCreateError(null);
    try {
      const stage = await clientFetch<TournamentStageOut>(`/api/admin/tournaments/${tournamentId}/stages`, {
        method: "POST",
        body: JSON.stringify({ name: newName.trim(), games_count: gamesCount, is_final: newIsFinal }),
      });
      setNewName("");
      setNewGamesCount("1");
      setNewIsFinal(false);
      reload();
      setOpenStageId(stage.id);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Не удалось создать этап");
    } finally {
      setCreating(false);
    }
  }

  async function markFinal(stage: TournamentStageOut) {
    // Отметить финальным можно только один этап разом -- сервер сам снимает
    // отметку с предыдущего (см. tournament_service._unset_other_final_stages).
    await clientFetch(`/api/admin/tournaments/${tournamentId}/stages/${stage.id}`, {
      method: "PUT",
      body: JSON.stringify({ is_final: true }),
    });
    reload();
  }

  return (
    <div className="rounded-card border border-ink-800 bg-ink-900/60 p-5">
      <h2 className="font-display text-lg text-ink-50">Этапы</h2>
      <p className="mt-1 max-w-xl text-sm text-ink-400">
        Нужны только если участников больше 10 и турнир играется отборочными столами по
        олимпийской системе. У каждого этапа сразу указывается число игр — под них создаются
        пустые слоты, которые потом оцениваются по мере проведения. Финальным можно отметить
        только один этап — на публичной странице турнира его таблица развёрнута по умолчанию,
        остальные свёрнуты.
      </p>

      {error && <p className="mt-3 text-sm text-brand-300">{error}</p>}

      <form onSubmit={handleCreate} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-400">
          Название этапа
          <input
            className={field}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Отборочный стол 1"
            maxLength={150}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-400">
          Число игр
          <input
            className={`${field} w-24 no-spinner`}
            type="number"
            min={1}
            max={64}
            value={newGamesCount}
            onChange={(e) => setNewGamesCount(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 pb-2.5 text-xs font-medium text-ink-400">
          <input
            type="checkbox"
            className="h-4 w-4 accent-brand-600"
            checked={newIsFinal}
            onChange={(e) => setNewIsFinal(e.target.checked)}
          />
          Финальный этап
        </label>
        <Button
          type="submit"
          variant="secondary"
          disabled={creating || !newName.trim()}
          className="!px-4"
        >
          <Plus size={16} />
          {creating ? "Добавляем…" : "Добавить этап"}
        </Button>
      </form>
      {createError && <p className="mt-2 text-sm text-brand-300">{createError}</p>}

      {stages === null && <p className="mt-4 text-sm text-ink-500">Загрузка…</p>}
      {stages?.length === 0 && (
        <p className="mt-4 text-sm text-ink-500">Этапов нет — турнир играется единой таблицей.</p>
      )}

      {stages && stages.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2">
          {stages.map((stage) => (
            <li key={stage.id} className="rounded-card border border-ink-800 bg-ink-900">
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <button
                  type="button"
                  onClick={() => setOpenStageId(openStageId === stage.id ? null : stage.id)}
                  className="flex flex-1 items-center gap-2.5 text-left"
                >
                  {openStageId === stage.id ? (
                    <CaretUp size={16} className="shrink-0 text-ink-500" />
                  ) : (
                    <CaretDown size={16} className="shrink-0 text-ink-500" />
                  )}
                  <span className="text-sm text-ink-50">{stage.name}</span>
                  {stage.is_final && (
                    <span className="rounded-pill bg-brand-900/40 px-2.5 py-0.5 text-xs text-brand-300">
                      Финал
                    </span>
                  )}
                  <span className="font-mono text-xs text-ink-500">{stage.games_count} оценённых</span>
                </button>
                {!stage.is_final && (
                  <button
                    onClick={() => markFinal(stage)}
                    title="Отметить финальным"
                    className="rounded-lg p-2 text-ink-400 hover:bg-ink-800 hover:text-ink-50"
                  >
                    <Flag size={16} />
                  </button>
                )}
                <button
                  onClick={() => del.ask(stage)}
                  title="Удалить этап"
                  className="rounded-lg p-2 text-ink-400 hover:bg-brand-900/40 hover:text-brand-300"
                >
                  <Trash size={16} />
                </button>
              </div>
              {openStageId === stage.id && (
                <div className="flex flex-col gap-6 border-t border-ink-800 p-4">
                  <StageGamesPanel tournamentId={tournamentId} stageId={stage.id} onGamesChanged={reload} />
                  <StageAdvancesPanel tournamentId={tournamentId} stage={stage} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={del.target !== null}
        title={`Удалить этап «${del.target?.name}»?`}
        description="Пустые (неоценённые) слоты этапа удалятся вместе с ним. Если на этапе уже есть оценённые игры, удаление отклонится — сначала перенесите их на другой этап."
        confirmLabel="Удалить этап"
        busy={del.busy}
        error={del.error}
        onConfirm={del.run}
        onCancel={del.close}
      />
    </div>
  );
}

/** Список слотов конкретного этапа + форма "добавить ещё". onGamesChanged
 * дёргает список этапов заново, чтобы обновился счётчик оценённых игр. */
function StageGamesPanel({
  tournamentId,
  stageId,
  onGamesChanged,
}: {
  tournamentId: number;
  stageId: number;
  onGamesChanged: () => void;
}) {
  const games = useResource<TournamentStageGameOut[]>(
    `/api/admin/tournaments/${tournamentId}/stages/${stageId}/games`,
    "Не удалось загрузить игры"
  );

  function reload() {
    games.reload();
    onGamesChanged();
  }

  return (
    <div>
      <p className="text-xs font-medium text-ink-400">Игры этапа</p>
      {games.error && <p className="mt-2 text-sm text-brand-300">{games.error}</p>}
      <div className="mt-2">
        <AddGamesForm
          addUrl={`/api/admin/tournaments/${tournamentId}/stages/${stageId}/games`}
          onAdded={reload}
        />
      </div>
      <div className="mt-3">
        {games.data === null ? (
          <p className="text-sm text-ink-500">Загрузка…</p>
        ) : (
          <GameSlotList games={games.data} onChanged={reload} />
        )}
      </div>
    </div>
  );
}

/** Сводная таблица этапа + чекбоксы "прошёл дальше". Один общий Save на всю
 * таблицу разом -- по описанию клуба, отметка ставится один раз, когда все
 * игры этапа уже сыграны, а не по ходу дела на каждую игру отдельно. */
function StageAdvancesPanel({
  tournamentId,
  stage,
}: {
  tournamentId: number;
  stage: TournamentStageOut;
}) {
  const [rows, setRows] = useState<TournamentStandingOut[] | null>(null);
  // Сводная таблица знает только slug (публичный контракт не отдаёт числовой
  // id игрока), а PUT .../advances принимает player_id -- берём соответствие
  // из /api/admin/players, как это уже делает game-form.tsx.
  const [playerIdBySlug, setPlayerIdBySlug] = useState<Map<string, number>>(new Map());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([
      clientFetch<TournamentStandingOut[]>(
        `/api/admin/tournaments/${tournamentId}/stages/${stage.id}/standings`
      ),
      clientFetch<{ id: number; slug: string }[]>("/api/admin/players"),
    ])
      .then(([list, players]) => {
        setRows(list);
        setPlayerIdBySlug(new Map(players.map((p) => [p.slug, p.id])));
        setSelected(new Set(list.filter((r) => r.advanced).map((r) => r.slug)));
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }, [tournamentId, stage.id]);

  function toggle(slug: string) {
    setSaved(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  async function handleSave() {
    if (!rows) return;
    setSaving(true);
    setError(null);
    const player_ids = [...selected]
      .map((slug) => playerIdBySlug.get(slug))
      .filter((id): id is number => id !== undefined);
    try {
      await clientFetch(`/api/admin/tournaments/${tournamentId}/stages/${stage.id}/advances`, {
        method: "PUT",
        body: JSON.stringify({ player_ids }),
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  if (error && !rows) return <p className="text-sm text-brand-300">{error}</p>;
  if (!rows) return <p className="text-sm text-ink-500">Загрузка…</p>;

  return (
    <div>
      <p className="text-xs font-medium text-ink-400">Сводная таблица этапа</p>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-ink-500">В этом этапе ещё нет оценённых игр.</p>
      ) : (
        <>
          <p className="mt-1 text-xs text-ink-500">
            Отметьте, кто проходит на следующий этап, и сохраните — отметка ставится один раз,
            когда все игры этапа уже внесены.
          </p>
          <div className="mt-3 overflow-x-auto rounded-lg border border-ink-800">
            <table className="w-full min-w-[420px] border-collapse">
              <thead>
                <tr className="border-b border-ink-800 bg-ink-850 text-left text-xs font-medium text-ink-400">
                  <th className="px-3 py-2 w-10">#</th>
                  <th className="px-3 py-2">Игрок</th>
                  <th className="px-3 py-2 text-right">Итог</th>
                  <th className="px-3 py-2 text-center w-28">Прошёл дальше</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {rows.map((row) => (
                  <tr key={row.slug} className="odd:bg-ink-900/40">
                    <td className="px-3 py-2 font-mono text-xs text-ink-400">{row.rank}</td>
                    <td className="px-3 py-2 text-sm text-ink-100">{row.nickname}</td>
                    <td className="px-3 py-2 text-right font-mono text-sm text-ink-50">{formatDash(row.total_score)}</td>
                    <td className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-brand-600"
                        checked={selected.has(row.slug)}
                        onChange={() => toggle(row.slug)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {error && <p className="mt-2 text-sm text-brand-300">{error}</p>}
          <div className="mt-3 flex items-center gap-3">
            <Button type="button" variant="secondary" onClick={handleSave} disabled={saving} className="!px-4 !py-2 text-xs">
              {saving ? "Сохраняем…" : "Сохранить прошедших"}
            </Button>
            {saved && <span className="text-xs text-ink-500">Сохранено.</span>}
          </div>
        </>
      )}
    </div>
  );
}
