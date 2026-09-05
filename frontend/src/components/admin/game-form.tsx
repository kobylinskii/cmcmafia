"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { fromClubDatetimeLocal, toDatetimeLocalValue } from "@/lib/format";
import type {
  GameOut,
  GameType,
  GameResult,
  GameRosterEntry,
  InGameRole,
  ParticipantInfo,
  ParticipantOut,
} from "@/types/api";
import { RESULT_LABELS, ROLE_LABELS, INFO_LABELS, LH_SCALE } from "@/types/api";
import { PlayerCombobox } from "@/components/admin/player-combobox";

/** Тут создаются и правятся только бот-форматы -- турнирные игры заводятся
 * целиком во вкладке «Турниры» (см. TournamentStagesManager), а привязку к
 * турниру/этапу уже существующего слота эта форма не меняет (см. пояснение
 * в game_service.update_rated_game на бэкенде). */
const CREATABLE_GAME_TYPE_LABELS: Record<Exclude<GameType, "tournament">, string> = {
  funky: "Фанки",
  training: "Обучающая",
};

type Row = {
  seat_number: number;
  player_id: number | "";
  role: InGameRole;
  points_win: string;
  points_judge: string;
  lh: string;
  ci: string;
  info: ParticipantInfo | "";
  removals: string;
  ppk: boolean;
  zk: string;
  sk: string;
};

const DEFAULT_ROLES: InGameRole[] = ["don", "mafia", "mafia", "sheriff", "citizen", "citizen", "citizen", "citizen", "citizen", "citizen"];

function emptyRows(): Row[] {
  return Array.from({ length: 10 }, (_, i) => ({
    seat_number: i + 1,
    player_id: "",
    role: DEFAULT_ROLES[i],
    points_win: "0",
    points_judge: "0",
    lh: "",
    ci: "",
    info: "",
    removals: "",
    ppk: false,
    zk: "",
    sk: "",
  }));
}

type SelectablePlayer = { id: number; slug: string; nickname: string; is_active: boolean };

/** Раскладывает уже внесённый результат по местам 1..10. Мержится поверх
 * emptyRows(), а не заменяет их: игра, пришедшая из бота, ещё не имеет ни
 * одного participant, и без этого таблица рендерилась бы вообще без строк --
 * оценить такую игру было нельзя. */
function rowsFromParticipants(
  participants: ParticipantOut[],
  playerIdBySlug: Map<string, number>
): Row[] {
  const bySeat = new Map(participants.map((p) => [p.seat_number, p]));
  return emptyRows().map((row) => {
    const p = bySeat.get(row.seat_number);
    if (!p) return row;
    return {
      seat_number: p.seat_number,
      player_id: playerIdBySlug.get(p.player_slug) ?? "",
      role: p.role,
      points_win: String(p.points_win),
      points_judge: String(p.points_judge),
      lh: p.lh === null ? "" : String(p.lh),
      ci: p.ci === null ? "" : String(p.ci),
      info: p.info ?? "",
      removals: p.removals === null ? "" : String(p.removals),
      ppk: p.ppk,
      zk: p.zk === null ? "" : String(p.zk),
      sk: p.sk === null ? "" : String(p.sk),
    };
  });
}

const ROSTER_ROLE_LABELS: Record<GameRosterEntry["role"], string> = {
  host: "Ведущий",
  judge: "Судья",
  player: "Игрок",
};

const field =
  "rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-2 text-sm text-ink-50 focus:border-brand-500 focus:outline-none w-full";
const label = "flex flex-col gap-1.5 text-xs font-medium text-ink-400";

export function GameForm({ game }: { game?: GameOut & { id: number } }) {
  const router = useRouter();
  const isEdit = Boolean(game);

  const isTournamentGame = game?.game_type === "tournament";

  const [players, setPlayers] = useState<SelectablePlayer[]>([]);
  // Некотролируемое поле, а не useState: <input type="datetime-local"> отдаёт
  // e.target.value === "" для ЛЮБОГО ещё не полностью заполненного значения
  // (спека HTML -- .value валиден только когда указаны И дата, И время). При
  // controlled value это означало постоянный сброс: набрал дату, время ещё не
  // тронуто -> onChange приходит с "" -> React перерисовывает поле пустым,
  // стирая уже введённую дату -- выбрать время было буквально невозможно.
  const startsAtRef = useRef<HTMLInputElement>(null);
  const [location, setLocation] = useState(game?.location ?? "");
  const [gameType, setGameType] = useState<Exclude<GameType, "tournament">>(
    game && game.game_type !== "tournament" ? game.game_type : "funky"
  );
  const [result, setResult] = useState<GameResult | "">(game?.result ?? "");
  const [notes, setNotes] = useState(game?.notes ?? "");
  const [rows, setRows] = useState<Row[]>(emptyRows());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // /api/admin/players carries numeric ids the public /api/players list doesn't.
    clientFetch<SelectablePlayer[]>("/api/admin/players").then((all) => {
      const playerIdBySlug = new Map(all.map((p) => [p.slug, p.id]));

      // Скрытые (soft-deleted) игроки остаются доступны в выпадающих списках,
      // если они уже числятся в этой игре -- иначе их место при открытии формы
      // молча обнулялось бы, и админ сохранил бы игру с потерянным участником.
      const alreadyInGame = new Set<number>();
      game?.participants.forEach((p) => {
        const id = playerIdBySlug.get(p.player_slug);
        if (id !== undefined) alreadyInGame.add(id);
      });
      game?.roster.forEach((r) => alreadyInGame.add(r.player_id));
      setPlayers(all.filter((p) => p.is_active || alreadyInGame.has(p.id)));

      if (!game) return;
      if (game.participants.length > 0) {
        setRows(rowsFromParticipants(game.participants, playerIdBySlug));
      }
      // Игра из бота (game.roster не пуст, participants ещё нет) НЕ рассаживается
      // по местам автоматически: место за столом в реальной игре определяется
      // жеребьёвкой на самой встрече и никак не связано с порядком записи в
      // боте. Раньше форма расставляла записавшихся по местам 1..10 в этом
      // порядке -- получалась ложная информация, которую администратор потом
      // всё равно перепроверял и перетасовывал вручную. Список записавшихся
      // остаётся видимым отдельным блоком-справкой (см. ниже), а десять мест
      // заполняются вручную через поиск, как и для полностью новой игры.
    })
      // Без catch любая ошибка -- истёкшая сессия, обрыв сети, пятисотка --
      // оставляла админа перед формой с десятью пустыми списками и без
      // единого слова о том, что произошло.
      .catch(() =>
        setError("Не удалось загрузить список игроков. Обновите страницу и попробуйте снова.")
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const usedPlayerIds = useMemo(() => new Set(rows.map((r) => r.player_id).filter(Boolean)), [rows]);

  function updateRow(index: number, patch: Partial<Row>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!result) {
      setError("Укажите исход игры");
      return;
    }
    const playerIds = rows.map((r) => r.player_id);
    if (playerIds.some((id) => id === "")) {
      setError("Заполните всех 10 участников");
      return;
    }
    if (new Set(playerIds).size !== 10) {
      setError("Игрок не может занимать больше одного места");
      return;
    }
    // Те же правила, что и на бэкенде (game_service._validate_participants) --
    // здесь только чтобы показать их сразу, не гоняя форму на сервер.
    const roleCounts = rows.reduce<Record<string, number>>(
      (acc, r) => ({ ...acc, [r.role]: (acc[r.role] ?? 0) + 1 }),
      {}
    );
    const expected: Record<string, number> = { don: 1, mafia: 2, sheriff: 1, citizen: 6 };
    if (Object.entries(expected).some(([role, n]) => roleCounts[role] !== n)) {
      setError("Состав ролей должен быть: 1 дон, 2 мафии, 1 шериф, 6 мирных");
      return;
    }
    if (rows.filter((r) => r.info === "first_killed").length > 1) {
      setError("Первоубиенный в игре может быть только один");
      return;
    }
    if (rows.some((r) => r.lh !== "" && r.info !== "first_killed")) {
      setError("ЛХ заполняется только у первоубиенного");
      return;
    }

    const participants = rows.map((r) => ({
      player_id: r.player_id as number,
      seat_number: r.seat_number,
      role: r.role,
      points_win: Number(r.points_win || 0),
      points_judge: Number(r.points_judge || 0),
      lh: r.lh === "" ? null : Number(r.lh),
      ci: r.ci === "" ? null : Number(r.ci),
      info: r.info || null,
      removals: r.removals === "" ? null : Number(r.removals),
      ppk: r.ppk,
      zk: r.zk === "" ? null : Number(r.zk),
      sk: r.sk === "" ? null : Number(r.sk),
    }));

    const payload = {
      // Парная к toDatetimeLocalValue: поле заполнено клубным временем, и
      // читать его надо тоже как клубное. new Date("2026-08-26T18:00")
      // трактует строку как локальное время браузера -- админ не из
      // Москвы сдвигал время игры каждым сохранением.
      starts_at: fromClubDatetimeLocal(startsAtRef.current!.value),
      location: location || null,
      // Турнирную игру формат не меняет: привязка к турниру/этапу
      // зафиксирована при создании слота и через эту форму не трогается
      // (см. game_service.update_rated_game на бэкенде).
      ...(isTournamentGame ? {} : { game_type: gameType }),
      result,
      notes: notes || null,
      participants,
    };

    setLoading(true);
    try {
      if (isEdit) {
        await clientFetch(`/api/admin/games/${game!.id}`, { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await clientFetch("/api/admin/games", { method: "POST", body: JSON.stringify(payload) });
      }
      router.push("/mafia/admin/games");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить игру");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-8">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className={label}>
          Дата и время
          <input
            ref={startsAtRef}
            type="datetime-local"
            className={field}
            defaultValue={game ? toDatetimeLocalValue(game.starts_at) : undefined}
            required
          />
        </label>
        <label className={label}>
          Место
          <input className={field} value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
        {isTournamentGame ? (
          <div className={label}>
            Турнир
            <div className={`${field} flex items-center gap-1.5 bg-ink-850 text-ink-300`}>
              <span>{game!.tournament!.name}</span>
              {game!.stage && <span className="text-ink-500">· {game!.stage.name}</span>}
            </div>
            <span className="font-normal text-ink-500">
              Привязку к турниру и этапу меняют в разделе «Турниры», не здесь.
            </span>
          </div>
        ) : (
          <label className={label}>
            Формат
            <select
              className={field}
              value={gameType}
              onChange={(e) => setGameType(e.target.value as Exclude<GameType, "tournament">)}
            >
              {Object.entries(CREATABLE_GAME_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className={label}>
          Исход
          <select className={field} value={result} onChange={(e) => setResult(e.target.value as GameResult)} required>
            <option value="">Не выбран</option>
            {Object.entries(RESULT_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>

      {game && game.roster.length > 0 && game.participants.length === 0 && (
        <div className="rounded-card border border-ink-800 bg-ink-900 p-4">
          <p className="text-xs font-medium text-ink-400">
            Записались в боте
          </p>
          <ul className="mt-2.5 flex flex-wrap gap-2">
            {game.roster.map((r) => (
              <li
                key={r.player_id}
                className="rounded-pill border border-ink-700 bg-ink-850 px-3 py-1 text-xs text-ink-200"
              >
                {r.nickname}
                <span className="ml-1.5 text-ink-500">· {ROSTER_ROLE_LABELS[r.role]}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="overflow-x-auto rounded-card border border-ink-800">
        <table aria-label="Состав игры: места, роли и баллы" className="w-full min-w-[1180px] border-collapse">
          <thead>
            <tr className="border-b border-ink-800 bg-ink-900 text-left text-xs font-medium text-ink-400">
              <th scope="col" className="px-2 py-2.5 w-10">№</th>
              <th scope="col" className="px-2 py-2.5 w-48">Игрок</th>
              <th scope="col" className="px-2 py-2.5 w-28">Роль</th>
              <th scope="col" className="px-2 py-2.5 w-20">За победу</th>
              <th scope="col" className="px-2 py-2.5 w-20">От судей</th>
              <th scope="col" className="px-2 py-2.5 w-20" title="Сколько из трёх названных оказались чёрными">ЛХ (из 3)</th>
              <th scope="col" className="px-2 py-2.5 w-16">Ci</th>
              <th scope="col" className="px-2 py-2.5 w-32">Инфо</th>
              <th scope="col" className="px-2 py-2.5 w-20">Удаления</th>
              <th scope="col" className="px-2 py-2.5 w-16">ППК</th>
              <th scope="col" className="px-2 py-2.5 w-16">ЖК</th>
              <th scope="col" className="px-2 py-2.5 w-16">СК</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800">
            {rows.map((row, i) => (
              <tr key={row.seat_number}>
                <td className="px-2 py-1.5 font-mono text-sm text-ink-400">{row.seat_number}</td>
                <td className="px-2 py-1.5">
                  <PlayerCombobox
                    id={`seat-${row.seat_number}-player`}
                    value={row.player_id}
                    onChange={(player_id) => updateRow(i, { player_id })}
                    options={players.filter((p) => p.id === row.player_id || !usedPlayerIds.has(p.id))}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <select
                    aria-label={`Место ${row.seat_number}: роль`}
                    className={field}
                    value={row.role}
                    onChange={(e) => updateRow(i, { role: e.target.value as InGameRole })}
                  >
                    {Object.entries(ROLE_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <input aria-label={`Место ${row.seat_number}: баллы за победу`} className={`${field} no-spinner`} type="number" step="0.25" value={row.points_win} onChange={(e) => updateRow(i, { points_win: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input aria-label={`Место ${row.seat_number}: баллы от судей`} className={`${field} no-spinner`} type="number" step="0.25" value={row.points_judge} onChange={(e) => updateRow(i, { points_judge: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  {/* Попадания, а не баллы: судья считает «сколько из трёх
                      названных оказались чёрными». Свободное число 0..1.5
                      читалось как баллы и путало. */}
                  <select
                    aria-label={`Место ${row.seat_number}: ЛХ, попаданий из трёх`}
                    className={field}
                    value={row.lh}
                    onChange={(e) => updateRow(i, { lh: e.target.value })}
                  >
                    <option value="">—</option>
                    {LH_SCALE.map((step) => (
                      <option key={step.raw} value={String(step.raw)}>
                        {step.hits}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <input aria-label={`Место ${row.seat_number}: Ci`} className={`${field} no-spinner`} type="number" step="0.5" placeholder="—" value={row.ci} onChange={(e) => updateRow(i, { ci: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <select
                    aria-label={`Место ${row.seat_number}: инфо`}
                    className={field}
                    value={row.info}
                    onChange={(e) => updateRow(i, { info: e.target.value as ParticipantInfo | "" })}
                  >
                    <option value="">—</option>
                    {Object.entries(INFO_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <input aria-label={`Место ${row.seat_number}: удаления`} className={`${field} no-spinner`} type="number" min="0" placeholder="—" value={row.removals} onChange={(e) => updateRow(i, { removals: e.target.value })} />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input aria-label={`Место ${row.seat_number}: ППК`} type="checkbox" className="h-4 w-4 accent-brand-600" checked={row.ppk} onChange={(e) => updateRow(i, { ppk: e.target.checked })} />
                </td>
                <td className="px-2 py-1.5">
                  <input aria-label={`Место ${row.seat_number}: ЖК`} className={`${field} no-spinner`} type="number" step="0.5" min="0" placeholder="—" value={row.zk} onChange={(e) => updateRow(i, { zk: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input aria-label={`Место ${row.seat_number}: СК`} className={`${field} no-spinner`} type="number" step="0.5" min="0" placeholder="—" value={row.sk} onChange={(e) => updateRow(i, { sk: e.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <label className={label}>
        Заметка (не публикуется)
        <textarea className={`${field} min-h-20 resize-y max-w-xl`} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      {error && (
        <p role="alert" className="rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200">
          {error}
        </p>
      )}

      <div>
        <Button type="submit" disabled={loading}>
          {loading ? "Сохраняем…" : isEdit ? "Сохранить игру" : "Добавить игру"}
        </Button>
      </div>
    </form>
  );
}
