"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { List, ListChecks, Ranking, Trophy, X } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { Container } from "@/components/ui/container";
import { NavLogo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";

// Иконки нужны мобильному меню -- в выпадающей карточке пункт из одного
// слова читается как список ссылок, а не как разделы сайта. Те же значки, что
// в сайдбаре админки, чтобы разделы опознавались одинаково в обоих местах.
const LINKS = [
  { href: "/mafia/games", label: "Игры", icon: ListChecks },
  { href: "/mafia/tournaments", label: "Турниры", icon: Trophy },
  { href: "/mafia/rating", label: "Рейтинг", icon: Ranking },
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
    <>
      {/* Тап мимо меню закрывает его, не проваливаясь в ссылку под пальцем.
          Ловушка -- сестра шапки, а не её потомок: backdrop-blur делает
          <header> containing block для fixed-потомков, и внутри неё оверлей
          схлопывался в высоту самой шапки. Начинается под шапкой, чтобы не
          перехватывать повторный тап по бургеру и переключатель темы. */}
      {open && (
        <div
          aria-hidden
          onClick={() => setOpen(false)}
          className="fixed inset-x-0 top-[4.5rem] bottom-0 z-30 bg-black/25 md:hidden"
        />
      )}
      <header className="sticky top-0 z-40 border-b border-ink-800/80 bg-ink-950/85 backdrop-blur">
        <Container className="flex h-[4.5rem] items-center justify-between gap-2">
          <NavLogo />
          {/* Ссылки, переключатель темы и бургер -- один flex-ряд справа: так
              кнопка темы стоит на месте и на десктопе, и на мобильном, без
              второго экземпляра разметки. */}
          <div className="flex items-center gap-1">
            <nav className="hidden md:flex items-center gap-1">
              {LINKS.map((link) => {
                const active = pathname.startsWith(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={clsx(
                      "rounded-pill px-4 py-2 text-base font-medium transition-colors active:translate-y-px",
                      active ? "bg-brand-600 text-white" : "text-ink-200 hover:text-ink-50 hover:bg-ink-850"
                    )}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
            <ThemeToggle className="h-11 w-11" />
            <button
              ref={buttonRef}
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="md:hidden inline-flex h-11 w-11 items-center justify-center rounded-pill text-ink-100 hover:bg-ink-850"
              aria-label={open ? "Закрыть меню" : "Открыть меню"}
              aria-expanded={open}
              aria-controls="mobile-nav"
            >
              {open ? <X size={22} weight="regular" /> : <List size={22} weight="regular" />}
            </button>
          </div>
        </Container>
        {open && (
          <nav
            id="mobile-nav"
            aria-label="Разделы сайта"
            // Карточка у правого края -- под кнопкой, из которой её открыли, и
            // ровно по отступу Container (px-4). Раньше это была полоса во всю
            // ширину экрана с тремя строками во весь её размах.
            className="nav-popover absolute top-full right-4 z-40 mt-2 w-56 origin-top-right rounded-card border border-ink-800 bg-ink-950/95 p-1.5 shadow-[0_24px_50px_-24px_rgba(0,0,0,0.65)] backdrop-blur md:hidden"
          >
            {LINKS.map((link, i) => {
              const active = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setOpen(false)}
                  // Индекс -- для каскада появления, см. .nav-popover в globals.css.
                  style={{ "--i": i } as CSSProperties}
                  className={clsx(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-base font-medium transition-colors active:translate-y-px",
                    active ? "bg-brand-600 text-white" : "text-ink-200 hover:bg-ink-850 hover:text-ink-50"
                  )}
                >
                  <link.icon size={19} weight={active ? "fill" : "regular"} />
                  {link.label}
                </Link>
              );
            })}
          </nav>
        )}
      </header>
    </>
  );
}
