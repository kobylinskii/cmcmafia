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

/** Значение из URL, если оно входит в список допустимых, иначе undefined.
 *
 * Бэкенд объявляет такие параметры как Literal и на чужое значение отвечает
 * 422 -- а страница, не поймавшая его, превращается в 500 (та же история,
 * что и с intParam выше). Отбрасывать неизвестный фильтр честнее, чем
 * показывать посетителю ошибку сервера из-за опечатки в ссылке. */
export function oneOf<T extends string>(
  value: string | undefined,
  allowed: readonly T[]
): T | undefined {
  return value !== undefined && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

/** Календарная дата ГГГГ-ММ-ДД из URL -- ровно то, что принимает API.
 *
 * Проверяется и формат, и существование даты: "2026-13-45" в формат
 * укладывается, а датой не является, и до этой проверки такое значение
 * доезжало до бэкенда и роняло страницу в 500. */
export function isoDate(value: string | undefined): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const parsed = new Date(`${value}T00:00:00Z`);
  // toISOString обратно даёт ту же строку только у существующей даты:
  // 2026-02-31 нормализуется в 2026-03-03 и отсеивается здесь.
  return Number.isNaN(parsed.getTime()) || !parsed.toISOString().startsWith(value)
    ? undefined
    : value;
}
