import clsx from "clsx";
import { ReactNode } from "react";

export function StatTile({
  label,
  value,
  sub,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  className?: string;
}) {
  return (
    <div className={clsx("rounded-card border border-ink-800 bg-ink-900 p-5", className)}>
      <p className="font-mono text-2xl font-medium text-ink-50 md:text-3xl">{value}</p>
      <p className="mt-1 text-sm text-ink-400">{label}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-500">{sub}</p>}
    </div>
  );
}
