"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * Обновление query-параметров текущего маршрута. Пустое значение удаляет
 * ключ; `offset` сбрасывается всегда -- смена любого фильтра начинает выдачу
 * заново.
 */
export function useUpdateParams() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (patch: Record<string, string>) => {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(patch)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    params.delete("offset");
    router.push(`${pathname}?${params.toString()}`, { scroll: false });
  };
}
