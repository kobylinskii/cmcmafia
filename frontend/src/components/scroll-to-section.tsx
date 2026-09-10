"use client";

import { useEffect } from "react";

/**
 * Доводит прокрутку до нужного блока после перехода и удерживает её там, пока
 * страница догружается.
 *
 * Намерение передаётся через sessionStorage, а НЕ через якорь в адресе. Так
 * вышло не от хорошей жизни: с `#formula` роутер Next запоминал якорь за
 * маршрутом, и после посещения формулы обычная вкладка «Рейтинг» в шапке
 * (её ссылка -- /rating, без якоря) всё равно открывала страницу на
 * формуле, будто нажали не туда. Почистить адрес через history.replaceState
 * не выходит: роутер возвращает якорь обратно. Ключ в sessionStorage живёт
 * ровно один переход, в адрес не попадает и вкладкам ничего не ломает.
 *
 * Одного прыжка мало по двум причинам:
 *  * страница отдаётся стримингом (force-dynamic), и таблица рейтинга ниже по
 *    документу приходит уже после прыжка -- вёрстка вырастает, цель уезжает;
 *  * сразу после гидратации роутер Next сбрасывает прокрутку наверх, не меняя
 *    высоту документа.
 * Поэтому сверяется положение самой цели, а не высота страницы.
 */
export const SCROLL_TARGET_KEY = "mafia:scroll-to";

const HOLD_MS = 2500;
const TOLERANCE_PX = 2;

export function ScrollToSection() {
  useEffect(() => {
    let id: string | null = null;
    try {
      id = sessionStorage.getItem(SCROLL_TARGET_KEY);
      // Снимаем сразу: намерение одноразовое, иначе следующий заход на
      // страницу снова уехал бы к тому же блоку.
      if (id) sessionStorage.removeItem(SCROLL_TARGET_KEY);
    } catch {
      // Приватный режим или заблокированное хранилище -- просто не доводим.
    }
    if (!id) return;
    const targetId = id;

    let stop = false;
    const release = () => {
      stop = true;
    };
    const events = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    events.forEach((e) => window.addEventListener(e, release, { passive: true }));

    const deadline = Date.now() + HOLD_MS;

    function tick() {
      if (stop || Date.now() > deadline) return;
      const el = document.getElementById(targetId);
      if (el) {
        // scroll-margin-top цели -- её «своё место» под фиксированной шапкой,
        // scrollIntoView его учитывает.
        const wanted = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
        if (Math.abs(el.getBoundingClientRect().top - wanted) > TOLERANCE_PX) {
          el.scrollIntoView();
        }
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    return () => {
      stop = true;
      events.forEach((e) => window.removeEventListener(e, release));
    };
  }, []);

  return null;
}
