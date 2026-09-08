"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { DateField } from "@/components/ui/date-field";
import { toDateValue, fromClubDateValue } from "@/lib/format";
import { fieldLarge as field, fieldLabelLg as label } from "@/lib/ui";
import { useSlugSuggestion } from "@/lib/use-slug-suggestion";
import { SlugSuggestion } from "@/components/admin/slug-suggestion";
import type { TournamentAdminOut } from "@/types/api";

export function TournamentForm({ tournament }: { tournament?: TournamentAdminOut }) {
  const router = useRouter();
  const isEdit = Boolean(tournament);

  const [name, setName] = useState(tournament?.name ?? "");
  const [slug, setSlug] = useState(tournament?.slug ?? "");
  const [description, setDescription] = useState(tournament?.description ?? "");
  const [location, setLocation] = useState(tournament?.location ?? "");
  const [startsAt, setStartsAt] = useState(tournament ? toDateValue(tournament.starts_at) : "");
  const [endsAt, setEndsAt] = useState(tournament ? toDateValue(tournament.ends_at) : "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  const slugSuggest = useSlugSuggestion({
    endpoint: "/api/admin/tournaments/slug-suggestion",
    param: "name",
    isEdit,
    original: tournament?.name ?? "",
    slug,
    setSlug,
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    // Раньше пустые даты отсекал required у <input type="date">; у своего
    // календаря браузерной валидации нет, проверяем сами.
    if (!startsAt || !endsAt) {
      setError("Укажите даты начала и окончания турнира.");
      return;
    }
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
          onBlur={() => slugSuggest.onSourceBlur(name)}
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
            slugSuggest.markTouched();
          }}
          pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]"
          placeholder="kubok-vmk"
          required
        />
        {slugSuggest.suggestion && (
          <SlugSuggestion
            intro="Название изменилось. Предложение:"
            suggestion={slugSuggest.suggestion}
            onApply={slugSuggest.apply}
            onDismiss={slugSuggest.dismiss}
          />
        )}
        <span className="font-normal text-ink-500">Только латиница, цифры и дефис.</span>
      </label>

      {/* Контейнерный запрос, а не sm:: форма стоит в колонке 380px, и
          обычный медиазапрос втиснул бы две даты в эту ширину, ориентируясь
          на ширину ОКНА. Здесь решает ширина самой формы. */}
      <div className="grid grid-cols-1 gap-4 @md:grid-cols-2">
        <label className={label}>
          Начало турнира
          <DateField
            className={field}
            value={startsAt}
            onChange={setStartsAt}
          />
        </label>
        <label className={label}>
          Окончание турнира
          <DateField
            className={field}
            value={endsAt}
            onChange={setEndsAt}
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
