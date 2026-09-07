"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, clientFetch } from "@/lib/api";

/**
 * Загрузка данных из API в клиентском компоненте.
 *
 * `data` -- null пока грузится или после ошибки; `error` заполняется текстом
 * из ApiError. `reload()` повторяет запрос -- зовётся после мутаций. `setData`
 * -- для оптимистичного обновления без похода в сеть.
 *
 * `path === null` -- «ещё не пора грузить» (ленивая загрузка по раскрытию
 * блока): запрос не уходит, состояние остаётся пустым.
 */
export function useResource<T>(path: string | null, fallbackError = "Не удалось загрузить") {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (path === null) return;
    clientFetch<T>(path)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : fallbackError));
  }, [path, fallbackError]);

  useEffect(reload, [reload]);

  return { data, error, reload, setData } as const;
}
