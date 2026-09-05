import { LH_SCALE, type LhHits } from "@/types/api";
import { withCount } from "@/lib/format";

// Показываем и попадания, и баллы: 0/3 и 1/3 дают одинаковые ноль баллов, но
// это разные события, и в данных они лежат в разных корзинах -- подпись
// «баллы ЛХ» на обеих делала их неразличимыми на глаз.
export function LhDistribution({ distribution }: { distribution: Record<LhHits, number> }) {
  const max = Math.max(1, ...LH_SCALE.map((s) => distribution[s.hits]));

  return (
    <div className="grid grid-cols-4 gap-3">
      {LH_SCALE.map((step) => {
        const count = distribution[step.hits];
        const heightPct = Math.max(6, Math.round((count / max) * 100));
        return (
          <div key={step.hits} className="flex flex-col items-center gap-2">
            <div className="flex h-24 w-full items-end justify-center rounded-lg bg-ink-850">
              <div
                className="w-full rounded-lg bg-brand-600"
                style={{ height: `${heightPct}%` }}
                aria-hidden
              />
            </div>
            <p className="font-mono text-sm text-ink-100">{count}</p>
            <p className="text-center text-xs text-ink-500">
              {step.hits}
              <span className="block text-ink-600">
                {withCount(step.points, ["балл", "балла", "баллов"])}
              </span>
            </p>
          </div>
        );
      })}
    </div>
  );
}
