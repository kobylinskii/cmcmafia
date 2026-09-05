"use client";

import { useEffect, useRef } from "react";
import clsx from "clsx";
import { Warning } from "@phosphor-icons/react/dist/ssr";

/**
 * Замена window.confirm/alert: те выглядят как системная ошибка браузера,
 * не подчиняются теме сайта и на мобильных выезжают поверх всего.
 *
 * Ошибку самого действия показываем внутри окна, а не отдельным alert'ом --
 * иначе пользователь теряет контекст того, что именно не удалось удалить.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Удалить",
  cancelLabel = "Отмена",
  destructive = true,
  busy = false,
  error = null,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    document.addEventListener("keydown", onKeyDown);

    // Фон не должен уезжать под модалкой.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink-950/70 p-4 backdrop-blur-sm sm:items-center"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        className={clsx(
          "w-full max-w-md rounded-card border border-ink-700 bg-ink-900 p-6",
          // Внутренняя светлая грань + мягкая тень под цвет фона: край читается
          // как физический, без неонового свечения.
          "shadow-[0_24px_60px_-20px_rgba(0,0,0,0.75)] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
        )}
      >
        <div className="flex gap-3.5">
          <span
            className={clsx(
              "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-pill",
              destructive ? "bg-brand-900/50 text-brand-300" : "bg-ink-800 text-ink-300"
            )}
          >
            <Warning size={19} weight="duotone" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="confirm-dialog-title" className="font-display text-lg leading-snug text-ink-50">
              {title}
            </h2>
            {description && (
              <div className="mt-2 text-sm leading-relaxed text-ink-300">{description}</div>
            )}
          </div>
        </div>

        {error && (
          <p role="alert" className="mt-4 rounded-lg border border-brand-800 bg-brand-900/30 px-3.5 py-2.5 text-sm text-brand-200">
            {error}
          </p>
        )}

        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-pill border border-ink-700 px-4 py-2.5 text-sm font-medium text-ink-200 transition-colors hover:border-ink-500 hover:text-ink-50 active:translate-y-px disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={clsx(
              "rounded-pill px-4 py-2.5 text-sm font-medium text-ink-50 transition-colors active:translate-y-px disabled:opacity-60",
              destructive ? "bg-brand-600 hover:bg-brand-500" : "bg-ink-700 hover:bg-ink-600"
            )}
          >
            {busy ? "Удаляем…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
