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
        // Без sizes Next подставляет 100vw и тянет самый крупный кандидат
        // srcset -- в таблице их до полусотни на экран.
        <Image src={src} alt={nickname} fill sizes="32px" className="object-cover" />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-xs text-ink-300">
          {nickname.slice(0, 1).toUpperCase()}
        </span>
      )}
    </span>
  );
}
