"use client";

import Link from "next/link";
import { buttonClasses } from "@/components/ui/button";
import { SCROLL_TARGET_KEY } from "@/components/scroll-to-section";

/**
 * Кнопка «Подробнее о формуле». Ведёт на обычный /mafia/rating, а куда
 * прокрутить -- кладёт в sessionStorage: якорь в адресе роутер Next запоминает
 * за маршрутом, и потом вкладка «Рейтинг» в шапке тоже открывала страницу на
 * формуле (см. components/scroll-to-section.tsx).
 */
export function FormulaLink() {
  return (
    <Link
      href="/mafia/rating"
      className={buttonClasses("secondary")}
      onClick={() => {
        try {
          sessionStorage.setItem(SCROLL_TARGET_KEY, "formula");
        } catch {
          // Хранилище недоступно -- просто откроется верх страницы рейтинга.
        }
      }}
    >
      Подробнее о формуле
    </Link>
  );
}
