"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";

/**
 * Действие с подтверждением через `<ConfirmDialog>`.
 *
 * `target` -- что подтверждаем (null = диалог закрыт), `ask(x)` открывает,
 * `run()` выполняет `action` и закрывает при успехе, оставляя `error` при
 * неудаче. Снимает копипаст `toDelete`/`busy`/`error`/`confirmFn` из каждого
 * списка с удалением.
 */
export function useConfirmable<T>(
  action: (target: T) => Promise<void>,
  fallbackError = "Не удалось выполнить"
) {
  const [target, setTarget] = useState<T | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (target === null) return;
    setBusy(true);
    setError(null);
    try {
      await action(target);
      setTarget(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : fallbackError);
    } finally {
      setBusy(false);
    }
  }

  return {
    target,
    busy,
    error,
    ask: setTarget,
    close: () => {
      setTarget(null);
      setError(null);
    },
    run,
  } as const;
}
