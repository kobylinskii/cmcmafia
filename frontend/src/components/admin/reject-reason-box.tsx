"use client";

import { Button } from "@/components/ui/button";

/** Поле «причина отклонения» под карточкой заявки или правки. Причину видит
 * игрок в боте, поэтому пустую отправить нельзя. */
export function RejectReasonBox({
  reason,
  onReason,
  onCancel,
  onConfirm,
  confirmLabel,
  busy,
}: {
  reason: string;
  onReason: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  busy: boolean;
}) {
  return (
    <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950 p-4">
      <label className="flex flex-col gap-1.5 text-xs text-ink-400">
        Причина отклонения — её увидит игрок в боте
        <textarea
          autoFocus
          rows={2}
          value={reason}
          onChange={(e) => onReason(e.target.value)}
          placeholder="Например: ФИО не совпадает с указанным в заявке на пропуск"
          className="rounded-lg border border-ink-700 bg-ink-950 px-3.5 py-2.5 text-sm text-ink-50 focus:border-brand-500 focus:outline-none"
        />
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" className="!px-4 !py-2" onClick={onCancel}>
          Отмена
        </Button>
        <Button className="!px-4 !py-2" disabled={!reason.trim() || busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </div>
  );
}
