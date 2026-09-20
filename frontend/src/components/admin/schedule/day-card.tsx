"use client";

import { CaretRight } from "@phosphor-icons/react/dist/ssr";
import { Badge } from "@/components/ui/badge";
import { formatWeekday, plural, withCount } from "@/lib/format";
import type { ScheduleDayOut } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";

// Ведущий и двое судей сверх стола -- те же HOST_LIMIT/JUDGE_LIMIT, которыми
// registration_service отбивает четвёртого желающего в штаб.
const STAFF_SEATS_PER_GAME = 3;

/** Строка игрового дня: когда играем и насколько собрались.
 *
 * Одна на два места -- список «Игровые дни» в расписании и дашборд на обзоре.
 * Раньше это была вёрстка внутри панели расписания, и дашборд её бы дублировал:
 * два места, где «ср» и полоса набора разъезжаются по виду при первой же
 * правке.
 *
 * День недели рядом с датой не украшение: игровые дни клуба повторяются именно
 * по дням недели, и без подписи админ сверяется с календарём на каждой строке.
 */
export function DayCard({
  card,
  onOpen,
  compact = false,
}: {
  card: ScheduleDayOut;
  onOpen: () => void;
  compact?: boolean;
}) {
  const filled = card.seats > 0 ? Math.min(card.players / card.seats, 1) : 0;
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-900 p-4 text-left hover:border-brand-600/60"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <span className="font-medium text-ink-50">
            {formatWeekday(card.first_starts_at)} {card.day}
          </span>
          <span className="text-ink-500">
            {card.games_count} {plural(card.games_count, ["игра", "игры", "игр"])}
          </span>
          {!compact &&
            card.types.map((type) => (
              <Badge key={type} tone="outline">
                {GAME_TYPE_LABELS[type]}
              </Badge>
            ))}
          {card.awaiting_count > 0 && (
            <Badge tone="brand">Подтвердить: {card.awaiting_count}</Badge>
          )}
        </div>

        <div className="mt-2.5 flex items-center gap-3">
          {/* Полоса набора -- то, ради чего на этот экран и заходят: видно
              сразу, собираются столы или день стоит пустой. */}
          <div className="h-1.5 w-full max-w-48 overflow-hidden rounded-full bg-ink-800">
            <div
              className="h-full rounded-full bg-brand-500"
              style={{ width: `${Math.round(filled * 100)}%` }}
            />
          </div>
          <span className="shrink-0 text-xs text-ink-400">
            {card.players}/{card.seats} за столами
          </span>
        </div>

        <p className="mt-1.5 text-xs text-ink-500">
          {card.people === 0 ? (
            "Записей пока нет"
          ) : (
            <>
              {withCount(card.people, ["человек", "человека", "человек"])} придёт · штаб{" "}
              {card.staff}/{card.games_count * STAFF_SEATS_PER_GAME}
              {card.reserves > 0 && ` · резерв ${card.reserves}`}
            </>
          )}
        </p>
      </div>
      <CaretRight size={16} className="shrink-0 text-ink-500" />
    </button>
  );
}
