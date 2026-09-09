"use client";

import { Moon, Sun } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";

/**
 * Переключатель тёмной и светлой темы. Состояние живёт ровно в двух местах:
 * атрибут data-theme на <html> (его читает CSS) и кука theme (её читает
 * layout.tsx при следующем рендере на сервере, чтобы страница сразу пришла
 * в нужной теме). Никакого состояния React: разметка кнопки одинакова на
 * сервере и клиенте, нужную иконку выбирает CSS по data-theme -- поэтому нет
 * ни расхождения гидрации, ни кадра с чужой иконкой.
 */
export function ThemeToggle({ className }: { className?: string }) {
  function toggle() {
    const root = document.documentElement;
    const wasLight = root.dataset.theme === "light";
    if (wasLight) {
      delete root.dataset.theme;
    } else {
      root.dataset.theme = "light";
    }
    // Год -- чтобы выбор пережил не только вкладку. secure только на https:
    // на локальном http браузер молча выбросил бы такую куку.
    const secure = location.protocol === "https:" ? "; secure" : "";
    document.cookie = `theme=${wasLight ? "dark" : "light"}; path=/; max-age=31536000; samesite=lax${secure}`;
  }

  return (
    <button
      type="button"
      onClick={toggle}
      // Подпись статична: она описывает действие кнопки, а не текущую тему,
      // поэтому не зависит от состояния и не врёт до гидрации.
      aria-label="Переключить тему"
      title="Переключить тему"
      // Размер задаёт вызывающий: в шапке сайта это тач-цель 44px, в админке
      // кнопка меньше. Держать h-11 здесь и перебивать снаружи нельзя --
      // порядок классов в атрибуте на Tailwind не влияет, выигрывает тот, что
      // ниже в сгенерированном CSS.
      className={clsx(
        "inline-flex items-center justify-center rounded-pill text-ink-300 transition-colors hover:bg-ink-850 hover:text-ink-50 active:translate-y-px",
        className
      )}
    >
      <Sun size={20} weight="regular" className="theme-when-dark" />
      <Moon size={20} weight="regular" className="theme-when-light" />
    </button>
  );
}
