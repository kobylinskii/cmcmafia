export type RawSearchParams = Record<string, string | string[] | undefined>;

export function firstParam(params: RawSearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

/** Целочисленный параметр из URL, приведённый к допустимому диапазону.
 *
 * Раньше страницы делали просто Number(...): "abc" давало NaN, "0" и "-5"
 * уходили в API как есть, бэкенд отвечал честной 422 -- а пользователь видел
 * жёсткую 500, потому что ApiError на странице никто не ловил. Достаточно было
 * битой ссылки из чата или краулера. */
export function intParam(
  params: RawSearchParams,
  key: string,
  { def, min = 0, max }: { def: number; min?: number; max: number }
): number {
  const raw = Number(firstParam(params, key));
  if (!Number.isFinite(raw)) return def;
  return Math.min(max, Math.max(min, Math.trunc(raw)));
}
