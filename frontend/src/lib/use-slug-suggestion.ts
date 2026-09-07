"use client";

import { useState } from "react";
import { clientFetch } from "@/lib/api";

/**
 * Подбор slug по нику/названию (общее для форм игрока и турнира).
 *
 * У нового объекта подставляет сразу, у существующего только предлагает: slug
 * -- публичный адрес страницы, менять его молча нельзя. `markTouched()` -- как
 * только slug правят руками, автоподбор выключается.
 */
export function useSlugSuggestion({
  endpoint,
  param,
  isEdit,
  original,
  slug,
  setSlug,
}: {
  endpoint: string;
  param: string;
  isEdit: boolean;
  original: string;
  slug: string;
  setSlug: (value: string) => void;
}) {
  const [touched, setTouched] = useState(false);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSourceBlur(source: string) {
    setSuggestion(null);
    if (touched || !source.trim()) return;
    if (isEdit && source.trim() === original) return;
    setLoading(true);
    try {
      const res = await clientFetch<{ slug: string }>(
        `${endpoint}?${param}=${encodeURIComponent(source)}`
      );
      if (res.slug === slug) return;
      if (isEdit) setSuggestion(res.slug);
      else setSlug(res.slug);
    } catch {
      // не критично -- slug можно ввести руками
    } finally {
      setLoading(false);
    }
  }

  return {
    loading,
    suggestion,
    onSourceBlur,
    markTouched: () => setTouched(true),
    apply: () => {
      if (suggestion === null) return;
      setSlug(suggestion);
      setTouched(true);
      setSuggestion(null);
    },
    dismiss: () => setSuggestion(null),
  };
}
