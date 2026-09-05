"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { List, X } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { Container } from "@/components/ui/container";
import { NavLogo } from "@/components/logo";

const LINKS = [
  { href: "/mafia/games", label: "Игры" },
  { href: "/mafia/tournaments", label: "Турниры" },
  { href: "/mafia/rating", label: "Рейтинг" },
];

export function SiteNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Escape закрывает меню и возвращает фокус на кнопку -- иначе с клавиатуры
  // из открытого меню было не выйти, а фокус оставался на исчезнувшем узле.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <header className="sticky top-0 z-40 border-b border-ink-800/80 bg-ink-950/85 backdrop-blur">
      <Container className="flex h-[4.5rem] items-center justify-between">
        <NavLogo />
        <nav className="hidden md:flex items-center gap-1">
          {LINKS.map((link) => {
            const active = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={clsx(
                  "rounded-pill px-4 py-2 text-base font-medium transition-colors active:translate-y-px",
                  active ? "bg-brand-600 text-ink-50" : "text-ink-200 hover:text-ink-50 hover:bg-ink-850"
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="md:hidden inline-flex h-10 w-10 items-center justify-center rounded-pill text-ink-100 hover:bg-ink-850"
          aria-label={open ? "Закрыть меню" : "Открыть меню"}
          aria-expanded={open}
          aria-controls="mobile-nav"
        >
          {open ? <X size={22} weight="regular" /> : <List size={22} weight="regular" />}
        </button>
      </Container>
      {open && (
        <div id="mobile-nav" className="md:hidden border-t border-ink-800 bg-ink-950">
          <Container className="flex flex-col gap-1 py-3">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className={clsx(
                  "rounded-lg px-4 py-3 text-base font-medium",
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
