"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Gauge, Key, ListChecks, Trophy, UsersThree, SignOut } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { LogoMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { adminLogout, adminMe } from "@/lib/admin-auth";
import { ApiError } from "@/lib/api";

const NAV = [
  { href: "/mafia/admin", label: "Обзор", icon: Gauge, exact: true },
  { href: "/mafia/admin/games", label: "Игры", icon: ListChecks },
  { href: "/mafia/admin/tournaments", label: "Турниры", icon: Trophy },
  { href: "/mafia/admin/players", label: "Игроки", icon: UsersThree },
];

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [nickname, setNickname] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    adminMe()
      .then((me) => {
        if (!me.is_site_admin) {
          router.replace("/mafia/admin/login");
          return;
        }
        setNickname(me.nickname);
        setChecked(true);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/mafia/admin/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        // Сеть или 5xx: раньше здесь не менялось ничего, и админка навсегда
        // застревала на «Проверяем доступ…» без единого объяснения.
        setAuthError(err instanceof ApiError ? err.message : "Сервер недоступен");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleLogout() {
    await adminLogout().catch(() => undefined);
    router.push("/mafia/admin/login");
  }

  if (!checked) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-ink-950 px-4 text-center">
        {authError ? (
          <>
            <p className="text-sm text-brand-300">Не удалось проверить доступ: {authError}</p>
            <button
              type="button"
              onClick={() => router.refresh()}
              className="rounded-pill border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:border-ink-500"
            >
              Повторить
            </button>
          </>
        ) : (
          <p className="text-sm text-ink-500">Проверяем доступ…</p>
        )}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-ink-950">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-ink-800 bg-ink-900 md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <LogoMark size={44} />
          <span className="font-display text-sm text-ink-50">Админка</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {NAV.map((item) => {
            const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={clsx(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                  active ? "bg-brand-600 text-white" : "text-ink-300 hover:bg-ink-850 hover:text-ink-50"
                )}
              >
                <item.icon size={18} weight={active ? "fill" : "regular"} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-ink-800 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate px-3 py-1 text-xs text-ink-500">{nickname}</p>
            <ThemeToggle className="h-9 w-9 shrink-0" />
          </div>
          <Link
            href="/mafia/admin/password"
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm text-ink-300 hover:bg-ink-850 hover:text-ink-50"
          >
            <Key size={18} />
            Сменить пароль
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm text-ink-300 hover:bg-ink-850 hover:text-ink-50"
          >
            <SignOut size={18} />
            Выйти
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-ink-800 bg-ink-900 px-4 py-3 md:hidden">
          <div className="flex items-center gap-2">
            <LogoMark size={40} />
            <span className="font-display text-sm text-ink-50">Админка</span>
          </div>
          <div className="flex items-center gap-1">
            <ThemeToggle className="h-9 w-9" />
            <button onClick={handleLogout} className="px-2 text-sm text-ink-300">
              Выйти
            </button>
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-ink-800 bg-ink-900 px-3 py-2 md:hidden">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="shrink-0 rounded-pill px-3 py-1.5 text-xs font-medium text-ink-300 hover:bg-ink-850 hover:text-ink-50"
            >
              {item.label}
            </Link>
          ))}
          <Link
            href="/mafia/admin/password"
            className="shrink-0 rounded-pill px-3 py-1.5 text-xs font-medium text-ink-300 hover:bg-ink-850 hover:text-ink-50"
          >
            Пароль
          </Link>
        </nav>
        <main className="flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
