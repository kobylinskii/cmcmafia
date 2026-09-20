"use client";

import { CaretRight } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { Badge } from "@/components/ui/badge";
import { capitalize, formatWeekday, plural, withCount } from "@/lib/format";
import type { ScheduleDayOut } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";

// Стол на десять игроков плюс ведущий: меньше -- играть не во что, и это
// единственное число, которое решает, состоится день или нет.
const PEOPLE_FOR_A_GAME = 11;

/** Строка игрового дня: когда играем и набрался ли народ.
 *
 * Одна на два места -- список «Игровые дни» в расписании и дашборд на обзоре.
 *
 * Счётчик ровно один. Места по столам и размер штаба отсюда убраны: «10/50 за
 * столами» и «штаб 0/15» не отвечали ни на один вопрос, который задают этому
 * экрану, -- а вопрос один: наберутся ли одиннадцать человек. Кто на каком
 * столе и хватает ли судей, видно внутри дня.
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
  const enough = card.people >= PEOPLE_FOR_A_GAME;
  const missing = PEOPLE_FOR_A_GAME - card.people;
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-900 p-4 text-left hover:border-brand-600/60"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <span className="font-medium text-ink-50">
            {capitalize(formatWeekday(card.first_starts_at))}, {card.day}
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

        <p className="mt-1.5 text-sm">
          {card.people === 0 ? (
            <span className="text-ink-500">
              Никто не записан — на игру нужно {PEOPLE_FOR_A_GAME} человек
            </span>
          ) : (
            <>
              <span className={clsx("font-medium", enough ? "text-ink-100" : "text-ink-300")}>
                {withCount(card.people, ["человек", "человека", "человек"])} записано
              </span>
              <span className="text-ink-500">
                {enough
                  ? " — на игру хватает"
                  : ` — не хватает ещё ${withCount(missing, ["человека", "человек", "человек"])}`}
              </span>
            </>
          )}
        </p>
      </div>
      <CaretRight size={16} className="shrink-0 text-ink-500" />
    </button>
  );
}
