"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import clsx from "clsx";

const PAGE_SIZES: { value: string; label: string }[] = [
  { value: "5", label: "5" },
  { value: "10", label: "10" },
  { value: "25", label: "25" },
  { value: "all", label: "Все" },
];

export function PlayerGamesFilterBar() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const glimit = searchParams.get("glimit") ?? "10";

  const select = (value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("glimit", value);
    params.delete("goffset");
    router.push(`${pathname}?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="flex flex-col gap-1.5 text-xs text-ink-400">
      Показывать
      <div className="inline-flex w-fit rounded-pill border border-ink-700 bg-ink-850 p-1">
        {PAGE_SIZES.map((size) => (
          <button
            key={size.value}
            type="button"
            onClick={() => select(size.value)}
            aria-pressed={glimit === size.value}
            className={clsx(
              "rounded-pill px-3.5 py-1.5 text-sm font-medium transition-colors",
              glimit === size.value ? "bg-brand-600 text-ink-50" : "text-ink-300 hover:text-ink-50"
            )}
          >
            {size.label}
          </button>
        ))}
      </div>
    </div>
  );
}
