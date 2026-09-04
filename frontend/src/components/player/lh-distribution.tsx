// Судейская отметка "x/3" -> вклад в рейтинг (см. backend
// rating_service.LH_RATING_VALUE, здесь только подписи для счётчиков раздачи).
const BUCKETS: { key: "0" | "0.5" | "1" | "1.5"; label: string }[] = [
  { key: "0", label: "0/3 → 0" },
  { key: "0.5", label: "1/3 → 0" },
  { key: "1", label: "2/3 → 0.5" },
  { key: "1.5", label: "3/3 → 1" },
];

export function LhDistribution({ distribution }: { distribution: Record<"0" | "0.5" | "1" | "1.5", number> }) {
  const max = Math.max(1, ...BUCKETS.map((b) => distribution[b.key]));

  return (
    <div className="grid grid-cols-4 gap-3">
      {BUCKETS.map((bucket) => {
        const count = distribution[bucket.key];
        const heightPct = Math.max(6, Math.round((count / max) * 100));
        return (
          <div key={bucket.key} className="flex flex-col items-center gap-2">
            <div className="flex h-24 w-full items-end justify-center rounded-lg bg-ink-850">
              <div
                className="w-full rounded-lg bg-brand-600"
                style={{ height: `${heightPct}%` }}
                aria-hidden
              />
            </div>
            <p className="font-mono text-sm text-ink-100">{count}</p>
            <p className="text-center text-xs text-ink-500">ЛХ {bucket.label}</p>
          </div>
        );
      })}
    </div>
  );
}
