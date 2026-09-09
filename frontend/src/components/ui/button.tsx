import Link from "next/link";
import { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

type Variant = "primary" | "secondary" | "ghost";

const base =
  "inline-flex items-center justify-center gap-2 rounded-pill px-6 py-3 text-sm font-medium whitespace-nowrap transition-all duration-200 active:scale-[0.98] disabled:opacity-40 disabled:pointer-events-none";

const variants: Record<Variant, string> = {
  // Текст на красной заливке -- именно белый, не ink-50: в светлой теме
  // ink-50 становится почти чёрным, и на brand-600 контраст падает до 3:1.
  primary: "bg-brand-600 text-white hover:bg-brand-500 shadow-[0_0_0_1px_rgba(181,41,35,0.4)]",
  secondary:
    "bg-ink-850 text-ink-50 border border-ink-600 hover:border-ink-400 hover:bg-ink-800",
  ghost: "text-ink-100 hover:text-ink-50 hover:bg-ink-850",
};

/** Классы кнопки для случаев, когда нужен обычный <a>, а не next/link --
 * например, ссылка с якорем на другую страницу (см. rating-teaser). */
export function buttonClasses(variant: Variant = "primary", className?: string) {
  return clsx(base, variants[variant], className);
}

export function Button({
  variant = "primary",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; children: ReactNode }) {
  return (
    <button className={clsx(base, variants[variant], className)} {...props}>
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "primary",
  className,
  children,
}: {
  href: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={clsx(base, variants[variant], className)}>
      {children}
    </Link>
  );
}
