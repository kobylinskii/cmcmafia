"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { field, fieldLabel as label } from "@/lib/ui";
import { useSlugSuggestion } from "@/lib/use-slug-suggestion";
import { SlugSuggestion } from "@/components/admin/slug-suggestion";
import type { PlayerAdminOut, InGameRole } from "@/types/api";

const ROLE_OPTIONS: { value: InGameRole; label: string }[] = [
  { value: "mafia", label: "Мафия" },
  { value: "don", label: "Дон" },
  { value: "sheriff", label: "Шериф" },
  { value: "citizen", label: "Мирный" },
];

export function PlayerForm({ player }: { player?: PlayerAdminOut }) {
  const router = useRouter();
  const isEdit = Boolean(player);

  const [nickname, setNickname] = useState(player?.nickname ?? "");
  const [slug, setSlug] = useState(player?.slug ?? "");
  const [fullName, setFullName] = useState(player?.full_name ?? "");
  const [age, setAge] = useState(player?.age?.toString() ?? "");
  const [favoriteRole, setFavoriteRole] = useState<InGameRole | "">(player?.favorite_role ?? "");
  const [experience, setExperience] = useState(player?.experience ?? "");
  const [bio, setBio] = useState(player?.bio ?? "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const slugSuggest = useSlugSuggestion({
    endpoint: "/api/admin/players/slug-suggestion",
    param: "nickname",
    isEdit,
    original: player?.nickname ?? "",
    slug,
    setSlug,
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const payload = {
      nickname,
      slug,
      full_name: fullName || null,
      age: age ? Number(age) : null,
      favorite_role: favoriteRole || null,
      experience: experience || null,
      bio: bio || null,
    };
    try {
      if (isEdit) {
        await clientFetch(`/api/admin/players/${player!.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      } else {
        await clientFetch("/api/admin/players", { method: "POST", body: JSON.stringify(payload) });
      }
      router.push("/mafia/admin/players");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сохранить");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex max-w-xl flex-col gap-5">
      <label className={label}>
        Никнейм
        <input
          className={field}
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          onBlur={() => slugSuggest.onSourceBlur(nickname)}
          required
          minLength={2}
        />
      </label>

      <label className={label}>
        Slug (адрес страницы /mafia/…)
        <input
          className={field}
          value={slug}
          onChange={(e) => {
            setSlug(e.target.value);
            slugSuggest.markTouched();
          }}
          placeholder={slugSuggest.loading ? "Подбираем…" : "chef"}
          pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]"
          required
        />
        {slugSuggest.suggestion && (
          <SlugSuggestion
            intro="Ник изменился. Предложение:"
            suggestion={slugSuggest.suggestion}
            onApply={slugSuggest.apply}
            onDismiss={slugSuggest.dismiss}
          />
        )}
        <span className="font-normal text-ink-500">
          Только латиница, цифры и дефис. Автопредложение по нику — перевод, не транслит, проверьте вручную.
        </span>
      </label>

      <label className={label}>
        ФИО
        <input className={field} value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </label>

      <div className="grid grid-cols-2 gap-4">
        <label className={label}>
          Возраст
          <input
            type="number"
            min={5}
            max={100}
            className={`${field} no-spinner`}
            value={age}
            onChange={(e) => setAge(e.target.value)}
          />
        </label>
        <label className={label}>
          Любимая роль
          <select
            className={field}
            value={favoriteRole}
            onChange={(e) => setFavoriteRole(e.target.value as InGameRole | "")}
          >
            <option value="">Не указана</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className={label}>
        Игровой опыт
        <input
          className={field}
          value={experience}
          onChange={(e) => setExperience(e.target.value)}
          placeholder="Играет с 2023 года"
        />
      </label>

      <label className={label}>
        О себе
        <textarea
          className={`${field} min-h-28 resize-y`}
          value={bio}
          onChange={(e) => setBio(e.target.value)}
        />
      </label>

      {error && (
        <p role="alert" className="rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={loading}>
          {loading ? "Сохраняем…" : isEdit ? "Сохранить" : "Добавить игрока"}
        </Button>
      </div>
    </form>
  );
}
