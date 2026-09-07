// Общие классы полей форм. Раньше эти строки лежали копией в начале каждого
// файла формы и уже разъехались (px-2.5 / px-3.5, text-sm / text-base) --
// три варианта по плотности, а не случайный дрейф.

const FIELD_BASE =
  "rounded-lg border border-ink-700 bg-ink-900 text-ink-50 focus:border-brand-500 focus:outline-none";

/** Плотное поле для табличных форм оценки и карточек расписания. */
export const fieldDense = `${FIELD_BASE} w-full px-2.5 py-2 text-sm`;
/** Обычное поле одноколоночной формы. */
export const field = `${FIELD_BASE} px-3.5 py-2.5 text-sm`;
/** Крупное поле: смена пароля, форма турнира. */
export const fieldLarge = `${FIELD_BASE} px-3.5 py-2.5 text-base`;

/** Подпись поля в плотной форме. */
export const fieldLabel = "flex flex-col gap-1.5 text-xs font-medium text-ink-400";
/** Подпись поля в обычной/крупной форме. */
export const fieldLabelLg = "flex flex-col gap-1.5 text-sm font-medium text-ink-400";
