import Image from "next/image";
import clsx from "clsx";
import { mediaUrl } from "@/lib/api";

/** Аватар игрока 32px для таблиц: фото или первая буква ника. */
export function PlayerAvatar({
  photoUrl,
  nickname,
  className,
}: {
  photoUrl: string | null | undefined;
  nickname: string;
  className?: string;
}) {
  const src = mediaUrl(photoUrl);
  return (
    <span
      className={clsx(
        "relative h-8 w-8 shrink-0 overflow-hidden rounded-full bg-ink-800",
        className
      )}
    >
      {src ? (
        // sizes -- вдвое больше реальных 32px, и quality=90 вместо дефолтных
        // 75: в кружок 32px фото 605x800 ужимается в двадцать раз, и на этом
        // масштабе и низкое качество, и попадание ровно в 1x видны как мыло.
        // Даёт ~3 КБ на аватар вместо ~1 КБ -- на полсотни строк рейтинга это
        // сотня килобайт, зато лицо перестаёт быть пятном. Без sizes Next
        // подставил бы 100vw и тянул самый крупный кандидат srcset.
        <Image src={src} alt={nickname} fill sizes="64px" quality={90} className="object-cover" />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-xs text-ink-300">
          {nickname.slice(0, 1).toUpperCase()}
        </span>
      )}
    </span>
  );
}
