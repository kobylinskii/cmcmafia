"use client";

import { useSearchParams } from "next/navigation";
import { useUpdateParams } from "@/lib/nav";
import { SegmentedControl } from "@/components/ui/segmented-control";

const PAGE_SIZES = [
  { value: "5", label: "5" },
  { value: "10", label: "10" },
  { value: "25", label: "25" },
  { value: "all", label: "Все" },
];

export function PlayerGamesFilterBar() {
  const searchParams = useSearchParams();
  const update = useUpdateParams();
  const glimit = searchParams.get("glimit") ?? "10";

  return (
    <div className="flex flex-col gap-1.5 text-xs text-ink-400">
      Показывать
      <SegmentedControl
        options={PAGE_SIZES}
        value={glimit}
        onChange={(glimit) => update({ glimit, goffset: "" })}
        className="w-fit"
      />
    </div>
  );
}
