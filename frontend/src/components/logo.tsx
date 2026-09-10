import Image from "next/image";
import Link from "next/link";
import clsx from "clsx";

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
export function LogoMark({
  size = 40,
  priority = false,
  className,
}: {
  size?: number;
  priority?: boolean;
  /** Нужен там, где знак крупный и должен ужиматься на узком экране
   * (страница 404): width/height задают только внутренний размер картинки. */
  className?: string;
}) {
  return (
    <Image
      src="/logo/logo-badge.png"
      alt="Мафия ВМК"
      width={size}
      height={size}
      // logo-badge-img: в светлой теме CSS подменяет файл на вариант с
      // чернильными контурами (белые на бумаге не видны). См. globals.css.
      className={clsx("logo-badge-img", className)}
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
      className={clsx("logo-badge-img", className)}
    />
  );
}

/** Горизонтальный логотип со шляпой -- надпись «Мафия ВМК» уже внутри
 * картинки, поэтому текстовой подписи рядом в шапке больше нет. */
export function LogoWordmark({ className, priority }: { className?: string; priority?: boolean }) {
  return (
    <Image
      src="/logo/logo-hat-wide.png"
      alt="Мафия ВМК"
      width={1600}
      height={323}
      priority={priority}
      className={clsx("logo-wordmark-img", className)}
      // unoptimized: next/image пересжимает PNG по качеству 75, и на тонких
      // линиях шляпы это даёт видимую грязь. Файл 67 КБ и кэшируется с первой
      // загрузки на весь визит -- экономить тут нечего.
      unoptimized
    />
  );
}

export function NavLogo() {
  return (
    <Link href="/" className="flex items-center shrink-0">
      <LogoWordmark className="h-10 w-auto" priority />
    </Link>
  );
}
