import Image from "next/image";
import Link from "next/link";

/**
 * Shape rule for the whole site (design-taste-frontend skill 4.4, "shape
 * consistency lock"): buttons are full-pill, cards/panels are `rounded-card`
 * (16px), inputs are `rounded-lg` (8px). Followed everywhere below.
 */
export function LogoMark({ size = 40 }: { size?: number }) {
  return (
    <Image
      src="/logo/logo-square.png"
      alt="Мафия ВМК"
      width={size}
      height={size}
      className="rounded-full"
      priority
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
    />
  );
}

export function NavLogo() {
  return (
    <Link href="/mafia" className="flex items-center gap-2.5 shrink-0">
      <LogoWordmark className="h-12 w-auto" priority />
      <span className="font-display text-lg text-ink-50">Мафия ВМК</span>
    </Link>
  );
}
