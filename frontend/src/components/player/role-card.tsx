import clsx from "clsx";
import { formatPercent } from "@/lib/format";

export function RoleCard({
  label,
  games,
  winRate,
  tone,
}: {
  label: string;
  games: number;
  winRate: number | null;
  tone: "black" | "red";
}) {
  return (
    <div
      className={clsx(
        "rounded-card border p-5",
        tone === "black" ? "border-ink-700 bg-ink-950" : "border-brand-500/50 bg-brand-500/15"
      )}
    >
      <p className="text-sm font-medium text-ink-200">{label}</p>
      <div className="mt-3 flex items-end justify-between">
        <div>
          <p className="font-mono text-2xl font-medium text-ink-50">{games}</p>
          <p className="text-xs text-ink-500">игр</p>
        </div>
        <div className="text-right">
          <p className="font-mono text-2xl font-medium text-ink-50">{formatPercent(winRate)}</p>
          <p className="text-xs text-ink-500">побед</p>
        </div>
      </div>
    </div>
  );
}
