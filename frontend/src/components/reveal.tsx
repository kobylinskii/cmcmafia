"use client";

import { ReactNode, useEffect, useRef, useState } from "react";
import clsx from "clsx";

/**
 * Scroll-reveal stagger, canonical pattern (design-taste-frontend skill 5.C):
 * motivated by hierarchy (draw attention to content as it enters), not
 * decoration.
 *
 * Раньше это был motion/react. Библиотека приезжала в клиентский бандл целиком
 * -- отдельным чанком на 117 КБ из 973 КБ всего клиентского JS -- ради одного
 * перехода opacity 0->1 со сдвигом на 20px. IntersectionObserver плюс CSS-
 * переход дают ровно тот же эффект и ту же кривую, но входят в килобайт.
 *
 * prefers-reduced-motion обрабатывается в CSS (см. globals.css, .reveal): при
 * включённой настройке блок нарисован на месте с самого начала, независимо от
 * класса. Там же лежит и запасной вариант для выключенного JS -- <noscript> в
 * app/layout.tsx.
 */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    // Элемент, уже попавший в область просмотра к моменту гидрации (первый
    // экран), IntersectionObserver отметит своим первым же коллбеком -- сам,
    // без setState прямо в теле эффекта.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect(); // once: true
        }
      },
      { threshold: 0.3 } // amount: 0.3
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={clsx("reveal", shown && "reveal-in", className)}
      style={{ transitionDelay: `${delay}s` }}
    >
      {children}
    </div>
  );
}
