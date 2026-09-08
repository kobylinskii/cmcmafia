"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

export type PopupRect = { left: number; width: number; top: number; bottom: number; openUp: boolean };

/**
 * Координаты для выпадашки, которую рисуют порталом в body с position:fixed.
 * Портал -- потому что списки открываются из плотных таблиц и карточек: внутри
 * потока их резал бы overflow предка и перекрывали соседние строки.
 *
 * Возвращает координаты якоря (кнопки поля), пересчитывая их на скролле и
 * ресайзе, разворачивает список вверх, когда снизу не хватает места, и следит
 * за кликом мимо. Ширину меньше minWidth растягивает и прижимает к краю
 * экрана, чтобы календарь не уезжал за границу на узком телефоне.
 */
export function useAnchoredPopup({
  open,
  anchorRef,
  popupRef,
  onClose,
  maxHeight,
  minWidth = 0,
}: {
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  popupRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  maxHeight: number;
  minWidth?: number;
}): PopupRect | null {
  const [rect, setRect] = useState<PopupRect | null>(null);
  // В ref, а не в зависимости эффекта: обработчик обычно приходит новой
  // стрелкой на каждый рендер, и подписки пересоздавались бы вхолостую.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    function measure() {
      const el = anchorRef.current;
      if (!el) return;
      const box = el.getBoundingClientRect();
      const spaceBelow = window.innerHeight - box.bottom;
      const width = Math.min(Math.max(box.width, minWidth), window.innerWidth - 16);
      setRect({
        left: Math.max(8, Math.min(box.left, window.innerWidth - width - 8)),
        width,
        top: box.bottom,
        bottom: window.innerHeight - box.top,
        openUp: spaceBelow < maxHeight && box.top > spaceBelow,
      });
    }
    measure();
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (anchorRef.current?.contains(target)) return;
      if (popupRef.current?.contains(target)) return;
      onCloseRef.current();
    }
    document.addEventListener("mousedown", onPointerDown);
    // Список -- fixed, поэтому на скролле и ресайзе координаты якоря нужно
    // пересчитывать, иначе он останется висеть там, где был открыт.
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, anchorRef, popupRef, maxHeight, minWidth]);

  // Пока закрыто -- координат нет, даже если после прошлого открытия что-то
  // осталось в состоянии.
  return open ? rect : null;
}

/** Стиль позиционирования для самого портала. */
export function popupStyle(rect: PopupRect, maxHeight: number): React.CSSProperties {
  return {
    position: "fixed",
    left: rect.left,
    width: rect.width,
    maxHeight,
    ...(rect.openUp ? { bottom: rect.bottom, top: "auto" } : { top: rect.top, bottom: "auto" }),
  };
}
