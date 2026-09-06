"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toDateValue, fromClubDateValue } from "@/lib/format";
import type { TournamentAdminOut } from "@/types/api";

const field =
  "rounded-lg border border-ink-700 bg-ink-900 px-3.5 py-2.5 text-base text-ink-50 focus:border-brand-500 focus:outline-none";
const label = "flex flex-col gap-1.5 text-sm font-medium text-ink-400";

export function TournamentForm({ tournament }: { tournament?: TournamentAdminOut }) {
  const router = useRouter();
  const isEdit = Boolean(tournament);

  const [name, setName] = useState(tournament?.name ?? "");
  const [slug, setSlug] = useState(tournament?.slug ?? "");
  const [slugTouched, setSlugTouched] = useState(false);
  const [slugSuggestion, setSlugSuggestion] = useState<string | null>(null);
  const [description, setDescription] = useState(tournament?.description ?? "");
  const [location, setLocation] = useState(tournament?.location ?? "");
  const [startsAt, setStartsAt] = useState(tournament ? toDateValue(tournament.starts_at) : "");
  const [endsAt, setEndsAt] = useState(tournament ? toDateValue(tournament.ends_at) : "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  const originalName = tournament?.name ?? "";

  async function handleNameBlur() {
    setSlugSuggestion(null);
    if (slugTouched || !name.trim()) return;
    if (isEdit && name.trim() === originalName) return;
    try {
      const res = await clientFetch<{ slug: string }>(
        `/api/admin/tournaments/slug-suggestion?name=${encodeURIComponent(name)}`
      );
      if (res.slug === slug) return;
      // У существующего турнира slug -- публичный адрес страницы, молча его
      // менять нельзя; у нового просто подставляем.
      if (isEdit) setSlugSuggestion(res.slug);
      else setSlug(res.slug);
    } catch {
      // не критично -- slug можно ввести руками
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    setLoading(true);
    const payload = {
      name,
      slug,
      starts_at: fromClubDateValue(startsAt),
      ends_at: fromClubDateValue(endsAt),
      description: description || null,
      location: location || null,
    };
    try {
      if (isEdit) {
        // Остаёмся на той же странице: ниже формы живут этапы/игры турнира
        // (TournamentStagesManager), и уход на список турниров выглядел как
        // будто они "пропали" после сохранения -- хотя на деле просто менялась
        // страница.
        await clientFetch(`/api/admin/tournaments/${tournament!.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setSaved(true);
        router.refresh();
      } else {
        // Новый турнир сразу открывается в редактировании -- там же заводятся
        // этапы и игры, без лишнего перехода через список турниров.
        const created = await clientFetch<TournamentAdminOut>("/api/admin/tournaments", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        router.push(`/mafia/admin/tournaments/${created.id}/edit`);
        router.refresh();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить турнир");
    } finally {
      setLoading(false);
    }
  }

  return (
    // Без max-w-xl: форма живёт в своей колонке и её ширину задаёт
    // колонка, а не сама форма (см. страницу редактирования турнира).
    <form onSubmit={handleSubmit} className="@container flex flex-col gap-4">
      <label className={label}>
        Название
        <input
          className={field}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={handleNameBlur}
          required
          minLength={2}
          maxLength={150}
        />
      </label>

      <label className={label}>
        Slug (адрес страницы /mafia/tournaments/…)
        <input
          className={field}
          value={slug}
          onChange={(e) => {
            setSlug(e.target.value);
            setSlugTouched(true);
          }}
          pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]"
          placeholder="kubok-vmk"
          required
        />
        {slugSuggestion && (
          <span className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-800 bg-brand-900/25 px-3 py-2 font-normal text-ink-200">
            Название изменилось. Предложение:{" "}
            <code className="font-mono text-ink-50">{slugSuggestion}</code>
            <button
              type="button"
              onClick={() => {
                setSlug(slugSuggestion);
                setSlugTouched(true);
                setSlugSuggestion(null);
              }}
              className="rounded-pill bg-brand-600 px-3 py-1 text-xs font-medium text-ink-50 hover:bg-brand-500 active:translate-y-px"
            >
              Подставить
            </button>
            <span className="w-full text-ink-500">
              Меняя slug, вы меняете адрес страницы турнира — старые ссылки перестанут работать.
            </span>
          </span>
        )}
        <span className="font-normal text-ink-500">Только латиница, цифры и дефис.</span>
      </label>

      {/* Контейнерный запрос, а не sm:: форма стоит в колонке 380px, и
          обычный медиазапрос втиснул бы две даты в эту ширину, ориентируясь
          на ширину ОКНА. Здесь решает ширина самой формы. */}
      <div className="grid grid-cols-1 gap-4 @md:grid-cols-2">
        <label className={label}>
          Начало турнира
          <input
            type="date"
            className={field}
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
          />
        </label>
        <label className={label}>
          Окончание турнира
          <input
            type="date"
            className={field}
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            required
          />
          <span className="font-normal text-ink-500">
            Плейсхолдер для дат игр — точную дату каждой игры выставляют отдельно.
          </span>
        </label>
      </div>

      <label className={label}>
        Место проведения
        <input
          className={field}
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          maxLength={200}
          placeholder="ВМК МГУ, ауд. 685"
        />
      </label>

      <label className={label}>
        Описание
        <textarea
          className={`${field} min-h-28 resize-y`}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={4000}
          placeholder="Регламент, даты, кто участвует."
        />
      </label>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200"
        >
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={loading}>
          {loading ? "Сохраняем…" : isEdit ? "Сохранить турнир" : "Создать турнир"}
        </Button>
        {saved && <span className="text-sm text-ink-500">Сохранено.</span>}
      </div>
    </form>
  );
}
