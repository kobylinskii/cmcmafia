import Link from "next/link";
import { CalendarBlank, MapPin, Trophy } from "@phosphor-icons/react/dist/ssr";
import type { GameListItem } from "@/types/api";
import { GAME_TYPE_LABELS } from "@/types/api";
import { ResultBadge, Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/format";

export function GameCard({ game }: { game: GameListItem }) {
  return (
    // Строкой карточка выкладывается только с lg: на 640-1023px в ряд
    // становятся дата, адрес, название турнира и две плашки -- адрес рвался
    // в столбик из пяти строк. До lg карточка идёт колонкой.
    <Link
      href={`/mafia/games/${game.id}`}
      className="flex flex-col gap-3 rounded-card border border-ink-800 bg-ink-900 p-5 transition-colors hover:border-brand-600/60 lg:flex-row lg:items-center lg:justify-between"
    >
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:gap-4">
        <span className="inline-flex items-center gap-1.5 text-base text-ink-200">
          <CalendarBlank size={16} className="text-ink-400" />
          {formatDate(game.starts_at)}
        </span>
        {game.location && (
          <span className="inline-flex items-center gap-1.5 text-base text-ink-400">
            <MapPin size={16} />
            {game.location}
          </span>
        )}
        {game.tournament && (
          <span className="inline-flex items-center gap-1.5 text-base text-ink-300">
            <Trophy size={16} className="text-ink-500" />
            {game.tournament.name}
          </span>
        )}
        <Badge tone="outline">{GAME_TYPE_LABELS[game.game_type]}</Badge>
      </div>
      <ResultBadge result={game.result} />
    </Link>
  );
}
