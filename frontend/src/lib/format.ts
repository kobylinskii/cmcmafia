const CLUB_TZ = "Europe/Moscow";

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

export function formatDateLong(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

/** «ЧЧ:ММ» по клубному времени. */
export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

/** Local "YYYY-MM-DDTHH:mm" for <input type="datetime-local">, in club time. */
export function toDatetimeLocalValue(iso: string): string {
  const parts = new Intl.DateTimeFormat("sv-SE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: CLUB_TZ,
    hour12: false,
  }).formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

/** Local "YYYY-MM-DD" for <input type="date">, in club time. */
export function toDateValue(iso: string): string {
  return new Intl.DateTimeFormat("sv-SE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: CLUB_TZ,
  }).format(new Date(iso));
}

/** "YYYY-MM-DD" (клубная дата, введённая в <input type="date">) -> ISO-момент
 * полуночи этого дня по клубному времени. Москва живёт в фиксированном
 * +03:00 без переходов на летнее/зимнее с 2014 года, так что смещение можно
 * зашить напрямую, не таская по проекту библиотеку часовых поясов. */
export function fromClubDateValue(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00+03:00`).toISOString();
}

/** "YYYY-MM-DDTHH:mm" из <input type="datetime-local"> -> ISO-момент. Парная к
 * toDatetimeLocalValue и обязательная к применению вместе с ней.
 *
 * new Date("2026-08-26T18:00") по спецификации трактует строку без смещения
 * как ЛОКАЛЬНОЕ время браузера, а поле заполнено клубным. Пути туда и обратно
 * были несимметричны: админ, открывший игру не из Москвы и нажавший
 * «Сохранить» не трогая дату, сдвигал время игры -- из Новосибирска на −4
 * часа, из UTC на +3, и накапливалось это с каждым сохранением. */
export function fromClubDatetimeLocal(value: string): string {
  return new Date(`${value}:00+03:00`).toISOString();
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 1000) / 10}%`;
}

export function formatDash(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  // Через Intl, а не String(): в русской локали дробная часть отделяется
  // запятой, и «2.8» посреди страницы, где рядом formatNumber рисует «1 234»,
  // читалось как два разных стиля вёрстки чисел.
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

/** Русское склонение числительного.
 *
 * plural(1, ["игра","игры","игр"]) -> "игра"
 * plural(3, [...])                 -> "игры"
 * plural(11, [...])                -> "игр"
 *
 * Формы: [1, 2-4, 5-0]. Раньше эта логика жила локальной функцией в одном
 * файле со списком турниров, а на остальных страницах множественное число
 * было просто зашито строкой -- отсюда «1 игроков», «22 лет» и «2 раз». */
export function plural(count: number, forms: [string, string, string]): string {
  const abs = Math.abs(Math.trunc(count));
  const mod100 = abs % 100;
  if (mod100 > 10 && mod100 < 20) return forms[2];
  const mod10 = abs % 10;
  if (mod10 === 1) return forms[0];
  if (mod10 >= 2 && mod10 <= 4) return forms[1];
  return forms[2];
}

/** Число вместе со склонённым словом: withCount(3, [...]) -> "3 игры". */
export function withCount(count: number, forms: [string, string, string]): string {
  return `${formatNumber(count)} ${plural(count, forms)}`;
}
