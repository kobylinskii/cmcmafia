import Image from "next/image";
import Link from "next/link";

/**
 * Shape rule for the whole site (design-taste-frontend skill 4.4, "shape
 * consistency lock"): buttons are full-pill, cards/panels are `rounded-card`
 * (16px), inputs are `rounded-lg` (8px). Followed everywhere below.
 */
/** Круглый знак клуба. Тот же файл, что и в геро-блоке на главной
 * (logo-badge.png): у него прозрачный фон.
 *
 * Раньше здесь стоял logo-square.png -- единственный из четырёх логотипов без
 * альфа-канала, с запечённым тёмным фоном. Обрезанный в круг через
 * rounded-full, он превращался в тёмный диск, неразличимый на ink-950.
 * rounded-full тут больше не нужен и вреден: эмблема уже круглая, а клип по
 * границам бокса срезал бы ей внешнее кольцо. */
export function LogoMark({ size = 40, priority = false }: { size?: number; priority?: boolean }) {
  return (
    <Image
      src="/logo/logo-badge.png"
      alt="Мафия ВМК"
      width={size}
      height={size}
      // priority по умолчанию выключен: этот знак стоит в подвале и на
      // служебных экранах, предзагружать его вперёд контента незачем.
      priority={priority}
      // unoptimized: next/image пересжимает PNG в WebP/AVIF по качеству 75.
      // На фотографии это незаметно, а на тонких линиях герба и мелком
      // курсиве "ВМК" даёт видимую грязь и цветную рябь по краям -- то, на
      // что жаловались. Источник всего 166 КБ и один на весь сайт (тот же
      // файл, что в геро-блоке), так что отдать его как есть и не экономить
      // байты ценой качества -- разумный компромисс для знака бренда.
      unoptimized
    />
  );
}

export function LogoHorizontal({ className }: { className?: string }) {
  return (
    <Image
      src="/logo/logo-horizontal.png"
      alt="Мафия ВМК"
      width={652}
      height={340}
      className={className}
    />
  );
}

/** Full emblem in a circular badge (hat, MSU tower silhouette, wordmark and
 * "ВМК" signature) -- the red AND white artwork are both real, kept as-is,
 * used large e.g. the homepage hero visual. */
export function LogoBadge({ className, priority }: { className?: string; priority?: boolean }) {
  return (
    <Image
      src="/logo/logo-badge.png"
      alt="Эмблема клуба Мафия ВМК"
      width={1200}
      height={1200}
      priority={priority}
      className={className}
    />
  );
}

/** Same emblem, trimmed to a wide crop for compact placements (nav bar). */
export function LogoWordmark({ className, priority }: { className?: string; priority?: boolean }) {
  return (
    <Image
      src="/logo/logo-mark-wide.png"
      alt="Эмблема клуба Мафия ВМК"
      width={2000}
      height={1581}
      priority={priority}
      className={className}
      // unoptimized: та же причина, что у LogoMark (см. комментарий там) --
      // next/image пересжимает PNG по качеству 75, и на тонких линиях герба
      // с мелким курсивом это давало видимую грязь. Это самый частый запрос
      // на сайте (шапка на каждой странице), поэтому файл раньше был урезан
      // через sizes -- но раз задача теперь чёткость, а не байты, отдаём
      // оригинал: 240 КБ, кэшируется браузером с первой загрузки на весь
      // визит, а дальше эта же строка href переиспользуется на каждой
      // странице (Link, не полная перезагрузка), так что цена разовая.
      unoptimized
    />
  );
}

export function NavLogo() {
  return (
    <Link href="/mafia" className="flex items-center gap-2.5 shrink-0">
      <LogoWordmark className="h-14 w-auto" priority />
      <span className="font-display text-lg text-ink-50">Мафия ВМК</span>
    </Link>
  );
}
