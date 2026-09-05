"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";

export type ComboboxPlayer = { id: number; nickname: string };

/**
 * Поиск игрока по нику вместо выпадающего списка на весь клуб: в форме игры
 * десять таких полей, и пролистывать сотню ников десять раз подряд -- это то,
 * ради чего люди бросают админку. Значение остаётся числовым id, наружу
 * компонент выглядит как обычное поле формы.
 *
 * Список рендерится порталом в document.body с position:fixed по координатам
 * инпута, а не просто absolute внутри строки таблицы: десять полей стоят
 * плотно друг под другом, и список, открытый для верхней строки, раньше
 * рисовался поверх соседних строк таблицы, перекрывая их поле ввода целиком
 * (см. скриншот бага) -- в таблице это выглядело так, будто в чужой строке
 * появился залитый цветом «выбранный игрок». Порталом список всегда лежит
 * поверх всего документа независимо от overflow/z-index предков, а при
 * нехватке места снизу разворачивается вверх (актуально для последних строк
 * таблицы, где снизу only остаётся поле «Заметка»).
 */
export function PlayerCombobox({
  value,
  options,
  onChange,
  placeholder = "Начните вводить ник",
  id,
}: {
  value: number | "";
  options: ComboboxPlayer[];
  onChange: (value: number | "") => void;
  placeholder?: string;
  id?: string;
}) {
  const selected = options.find((p) => p.id === value) ?? null;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [rect, setRect] = useState<{ left: number; width: number; top: number; bottom: number; openUp: boolean } | null>(
    null
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Пока список закрыт, в поле стоит выбранный ник; открывая, показываем то,
  // что человек печатает.
  const inputValue = open ? query : selected?.nickname ?? "";

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = q ? options.filter((p) => p.nickname.toLowerCase().includes(q)) : options;
    return pool.slice(0, 50);
  }, [options, query]);

  const DROPDOWN_MAX_HEIGHT = 224; // max-h-56

  function measure() {
    const el = inputRef.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const spaceBelow = window.innerHeight - box.bottom;
    const openUp = spaceBelow < DROPDOWN_MAX_HEIGHT && box.top > spaceBelow;
    setRect({ left: box.left, width: box.width, top: box.bottom, bottom: window.innerHeight - box.top, openUp });
  }

  useEffect(() => {
    if (!open) return;
    measure();
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (inputRef.current?.contains(target)) return;
      if (listRef.current?.contains(target)) return;
      setOpen(false);
    }
    // Список -- fixed, поэтому при скролле/резайзе координаты входа нужно
    // пересчитывать заново, иначе он останется висеть там, где был открыт.
    function onReposition() {
      measure();
    }
    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("scroll", onReposition, true);
    window.addEventListener("resize", onReposition);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("scroll", onReposition, true);
      window.removeEventListener("resize", onReposition);
    };
  }, [open]);

  function choose(player: ComboboxPlayer) {
    onChange(player.id);
    setQuery("");
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((i) => (matches.length ? (i + delta + matches.length) % matches.length : 0));
    } else if (event.key === "Enter") {
      if (open && matches[activeIndex]) {
        event.preventDefault();
        choose(matches[activeIndex]);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  return (
    <div className="relative">
      <input
        ref={inputRef}
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={id ? `${id}-listbox` : undefined}
        value={inputValue}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setActiveIndex(0);
          setOpen(true);
        }}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
        className={clsx(
          "w-full rounded-lg border bg-ink-900 px-2.5 py-2 text-sm text-ink-50 focus:outline-none",
          selected ? "border-ink-700 focus:border-brand-500" : "border-brand-800 focus:border-brand-500"
        )}
      />

      {open &&
        rect &&
        createPortal(
          <ul
            ref={listRef}
            id={id ? `${id}-listbox` : undefined}
            role="listbox"
            style={{
              position: "fixed",
              left: rect.left,
              width: rect.width,
              maxHeight: DROPDOWN_MAX_HEIGHT,
              ...(rect.openUp ? { bottom: rect.bottom, top: "auto" } : { top: rect.top, bottom: "auto" }),
            }}
            className={clsx(
              "z-50 overflow-y-auto rounded-lg border border-ink-700 bg-ink-850 py-1 shadow-xl",
              rect.openUp ? "mb-1" : "mt-1"
            )}
          >
            {matches.length === 0 && (
              <li className="px-3 py-2 text-sm text-ink-500">Никого не нашли</li>
            )}
            {matches.map((player, i) => (
              <li
                key={player.id}
                role="option"
                aria-selected={player.id === value}
                onMouseEnter={() => setActiveIndex(i)}
                onMouseDown={(e) => {
                  // mousedown, а не click: blur инпута успел бы закрыть список.
                  e.preventDefault();
                  choose(player);
                }}
                className={clsx(
                  "cursor-pointer px-3 py-2 text-sm",
                  i === activeIndex ? "bg-brand-600 text-ink-50" : "text-ink-200"
                )}
              >
                {player.nickname}
              </li>
            ))}
          </ul>,
          document.body
        )}
    </div>
  );
}
