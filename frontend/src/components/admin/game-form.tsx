"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toDatetimeLocalValue } from "@/lib/format";
import type { GameOut, GameType, GameResult, InGameRole, ParticipantInfo } from "@/types/api";
import { GAME_TYPE_LABELS, RESULT_LABELS, ROLE_LABELS, INFO_LABELS } from "@/types/api";

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

const field =
  "rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-2 text-sm text-ink-50 focus:border-brand-500 focus:outline-none w-full";
const label = "flex flex-col gap-1.5 text-xs font-medium text-ink-400";

type SelectablePlayer = { id: number; slug: string; nickname: string; is_active: boolean };

export function GameForm({ game }: { game?: GameOut & { id: number } }) {
  const router = useRouter();
  const isEdit = Boolean(game);

  const [players, setPlayers] = useState<SelectablePlayer[]>([]);
  const [startsAt, setStartsAt] = useState(game ? toDatetimeLocalValue(game.starts_at) : "");
  const [location, setLocation] = useState(game?.location ?? "");
  const [gameType, setGameType] = useState<GameType>(game?.game_type ?? "tournament");
  const [result, setResult] = useState<GameResult | "">(game?.result ?? "");
  const [notes, setNotes] = useState(game?.notes ?? "");
  const [rows, setRows] = useState<Row[]>(emptyRows());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // /api/admin/players carries numeric ids the public /api/players list doesn't.
    clientFetch<{ id: number; slug: string; nickname: string; photo_url: string | null; is_active: boolean }[]>(
      "/api/admin/players"
    ).then((all) => {
      const active = all.filter((p) => p.is_active);
      setPlayers(active);
      if (game) {
        const bySlug = new Map(active.map((p) => [p.slug, p]));
        setRows(
          [...game.participants]
            .sort((a, b) => a.seat_number - b.seat_number)
            .map((p) => ({
              seat_number: p.seat_number,
              player_id: bySlug.get(p.player_slug)?.id ?? "",
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
            }))
        );
      }
    });
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
      starts_at: new Date(startsAt).toISOString(),
      location: location || null,
      game_type: gameType,
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
            type="datetime-local"
            className={field}
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
          />
        </label>
        <label className={label}>
          Место
          <input className={field} value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
        <label className={label}>
          Формат
          <select className={field} value={gameType} onChange={(e) => setGameType(e.target.value as GameType)}>
            {Object.entries(GAME_TYPE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
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

      <div className="overflow-x-auto rounded-card border border-ink-800">
        <table className="w-full min-w-[1180px] border-collapse">
          <thead>
            <tr className="border-b border-ink-800 bg-ink-900 text-left text-xs font-medium text-ink-400">
              <th className="px-2 py-2.5 w-10">№</th>
              <th className="px-2 py-2.5 w-48">Игрок</th>
              <th className="px-2 py-2.5 w-28">Роль</th>
              <th className="px-2 py-2.5 w-20">За победу</th>
              <th className="px-2 py-2.5 w-20">От судей</th>
              <th className="px-2 py-2.5 w-16">ЛХ</th>
              <th className="px-2 py-2.5 w-16">Ci</th>
              <th className="px-2 py-2.5 w-32">Инфо</th>
              <th className="px-2 py-2.5 w-20">Удаления</th>
              <th className="px-2 py-2.5 w-16">ППК</th>
              <th className="px-2 py-2.5 w-16">ЖК</th>
              <th className="px-2 py-2.5 w-16">СК</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800">
            {rows.map((row, i) => (
              <tr key={row.seat_number}>
                <td className="px-2 py-1.5 font-mono text-sm text-ink-400">{row.seat_number}</td>
                <td className="px-2 py-1.5">
                  <select
                    className={field}
                    value={row.player_id}
                    onChange={(e) => updateRow(i, { player_id: e.target.value ? Number(e.target.value) : "" })}
                    required
                  >
                    <option value="">Выберите</option>
                    {players
                      .filter((p) => p.id === row.player_id || !usedPlayerIds.has(p.id))
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.nickname}
                        </option>
                      ))}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <select className={field} value={row.role} onChange={(e) => updateRow(i, { role: e.target.value as InGameRole })}>
                    {Object.entries(ROLE_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" step="0.25" value={row.points_win} onChange={(e) => updateRow(i, { points_win: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" step="0.25" value={row.points_judge} onChange={(e) => updateRow(i, { points_judge: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" step="0.5" min="0" max="1.5" placeholder="—" value={row.lh} onChange={(e) => updateRow(i, { lh: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" step="0.5" placeholder="—" value={row.ci} onChange={(e) => updateRow(i, { ci: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <select className={field} value={row.info} onChange={(e) => updateRow(i, { info: e.target.value as ParticipantInfo | "" })}>
                    <option value="">—</option>
                    {Object.entries(INFO_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" min="0" placeholder="—" value={row.removals} onChange={(e) => updateRow(i, { removals: e.target.value })} />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={row.ppk} onChange={(e) => updateRow(i, { ppk: e.target.checked })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" step="0.5" min="0" placeholder="—" value={row.zk} onChange={(e) => updateRow(i, { zk: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <input className={field} type="number" step="0.5" min="0" placeholder="—" value={row.sk} onChange={(e) => updateRow(i, { sk: e.target.value })} />
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
