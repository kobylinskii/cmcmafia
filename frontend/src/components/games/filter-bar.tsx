"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import clsx from "clsx";
import { GAME_TYPE_LABELS, RESULT_LABELS } from "@/types/api";

const PAGE_SIZES = [10, 25, 50, 100];

function useUpdateParam() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    params.delete("offset");
    router.push(`${pathname}?${params.toString()}`);
  };
}

export function GamesFilterBar() {
  const searchParams = useSearchParams();
  const update = useUpdateParam();

  const limit = searchParams.get("limit") ?? "10";
  const gameType = searchParams.get("game_type") ?? "";
  const result = searchParams.get("result") ?? "";

  return (
    <div className="flex flex-col gap-6 rounded-card border border-ink-800 bg-ink-900 p-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="flex flex-1 flex-wrap gap-4">
        <label className="flex flex-col gap-1.5 text-xs text-ink-400">
          Формат
          <select
            value={gameType}
            onChange={(e) => update("game_type", e.target.value)}
            className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-sm text-ink-100 focus:border-brand-500 focus:outline-none"
          >
            <option value="">Все форматы</option>
            {Object.entries(GAME_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5 text-xs text-ink-400">
          Исход
          <select
            value={result}
            onChange={(e) => update("result", e.target.value)}
            className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-sm text-ink-100 focus:border-brand-500 focus:outline-none"
          >
            <option value="">Любой исход</option>
            {Object.entries(RESULT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-1.5 text-xs text-ink-400">
        Показывать последние
        {/* Was a <input type=range>: it fired a navigation on every drag tick,
            which could burst past the public API's rate limit and crash the
            page. A segmented control fires exactly one navigation per click. */}
        <div className="inline-flex rounded-pill border border-ink-700 bg-ink-850 p-1">
          {PAGE_SIZES.map((size) => (
            <button
              key={size}
              type="button"
              onClick={() => update("limit", String(size))}
              aria-pressed={limit === String(size)}
              className={clsx(
                "rounded-pill px-3.5 py-1.5 text-sm font-medium transition-colors",
                limit === String(size) ? "bg-brand-600 text-ink-50" : "text-ink-300 hover:text-ink-50"
              )}
            >
              {size}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
