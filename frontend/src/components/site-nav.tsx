"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { List, X } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { Container } from "@/components/ui/container";
import { NavLogo } from "@/components/logo";

const LINKS = [
  { href: "/mafia/games", label: "Игры" },
  { href: "/mafia/rating", label: "Рейтинг" },
];

export function SiteNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-ink-800/80 bg-ink-950/85 backdrop-blur">
      <Container className="flex h-16 items-center justify-between">
        <NavLogo />
        <nav className="hidden md:flex items-center gap-1">
          {LINKS.map((link) => {
            const active = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={clsx(
                  "rounded-pill px-4 py-2 text-sm font-medium transition-colors",
                  active ? "bg-brand-600 text-ink-50" : "text-ink-200 hover:text-ink-50 hover:bg-ink-850"
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="md:hidden inline-flex h-10 w-10 items-center justify-center rounded-pill text-ink-100 hover:bg-ink-850"
          aria-label={open ? "Закрыть меню" : "Открыть меню"}
        >
          {open ? <X size={22} weight="regular" /> : <List size={22} weight="regular" />}
        </button>
      </Container>
      {open && (
        <div className="md:hidden border-t border-ink-800 bg-ink-950">
          <Container className="flex flex-col gap-1 py-3">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className={clsx(
                  "rounded-lg px-4 py-3 text-sm font-medium",
                  pathname.startsWith(link.href) ? "bg-brand-600 text-ink-50" : "text-ink-200 hover:bg-ink-850"
                )}
              >
                {link.label}
              </Link>
            ))}
          </Container>
        </div>
      )}
    </header>
  );
}
