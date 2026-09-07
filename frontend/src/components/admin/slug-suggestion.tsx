"use client";

/** Плашка «название/ник изменились, вот предложение slug» под полем slug в
 * формах игрока и турнира. */
export function SlugSuggestion({
  intro,
  suggestion,
  onApply,
  onDismiss,
}: {
  intro: string;
  suggestion: string;
  onApply: () => void;
  onDismiss: () => void;
}) {
  return (
    <span className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-800 bg-brand-900/25 px-3 py-2 font-normal text-ink-200">
      {intro} <code className="font-mono text-ink-50">{suggestion}</code>
      <button
        type="button"
        onClick={onApply}
        className="rounded-pill bg-brand-600 px-3 py-1 text-xs font-medium text-ink-50 hover:bg-brand-500 active:translate-y-px"
      >
        Подставить
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="rounded-pill border border-ink-700 px-3 py-1 text-xs text-ink-300 hover:border-ink-500"
      >
        Оставить как есть
      </button>
      <span className="w-full text-ink-500">
        Меняя slug, вы меняете адрес страницы — старые ссылки перестанут работать.
      </span>
    </span>
  );
}
