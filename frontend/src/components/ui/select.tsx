"use client";

import { useCallback, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CaretDown } from "@phosphor-icons/react/dist/ssr";
import clsx from "clsx";
import { popupStyle, useAnchoredPopup } from "@/lib/use-anchored-popup";

export type SelectOption<T extends string> = { value: T; label: string };

/**
 * Замена нативному <select>. Нативный список на мобильных рисует не браузер, а
 * система: белый (или гугловский тёмно-серый) диалог с радиокнопками поверх
 * тёмного сайта -- см. скриншот. Раскладка списка здесь наша, как у
 * PlayerCombobox: портал в body с position:fixed по координатам кнопки, чтобы
 * список не резался overflow таблиц и карточек и разворачивался вверх, когда
 * снизу нет места.
 */
export function Select<T extends string>({
  value,
  options,
  onChange,
  className,
  disabled,
  id,
  "aria-label": ariaLabel,
}: {
  value: T;
  options: readonly SelectOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  const selected = options.find((o) => o.value === value) ?? null;
  const MAX_HEIGHT = 256; // max-h-64

  const close = useCallback(() => setOpen(false), []);
  const rect = useAnchoredPopup({
    open,
    anchorRef: buttonRef,
    popupRef: listRef,
    onClose: close,
    maxHeight: MAX_HEIGHT,
  });

  function openList() {
    setActiveIndex(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  }

  function choose(option: SelectOption<T>) {
    onChange(option.value);
    setOpen(false);
    buttonRef.current?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openList();
        return;
      }
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((i) => (i + delta + options.length) % options.length);
    } else if (open && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      const option = options[activeIndex];
      if (option) choose(option);
    }
  }

  return (
    <>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKeyDown}
        className={clsx(
          "flex w-full items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:text-ink-500",
          className
        )}
      >
        <span className="truncate">{selected?.label ?? ""}</span>
        <CaretDown
          size={14}
          weight="bold"
          className={clsx("shrink-0 text-ink-400 transition-transform", open && "rotate-180")}
        />
      </button>

      {open &&
        rect &&
        createPortal(
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            style={popupStyle(rect, MAX_HEIGHT)}
            className={clsx(
              "z-50 overflow-y-auto rounded-lg border border-ink-700 bg-ink-850 py-1 shadow-xl",
              rect.openUp ? "mb-1" : "mt-1"
            )}
          >
            {options.map((option, i) => (
              <li
                key={option.value}
                role="option"
                aria-selected={option.value === value}
                onMouseEnter={() => setActiveIndex(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(option);
                }}
                className={clsx(
                  "cursor-pointer px-3 py-2.5 text-sm",
                  i === activeIndex ? "bg-brand-600 text-white" : "text-ink-200"
                )}
              >
                {option.label}
              </li>
            ))}
          </ul>,
          document.body
        )}
    </>
  );
}
