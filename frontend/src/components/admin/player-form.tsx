"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientFetch, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { PlayerAdminOut, InGameRole } from "@/types/api";

const ROLE_OPTIONS: { value: InGameRole; label: string }[] = [
  { value: "mafia", label: "Мафия" },
  { value: "don", label: "Дон" },
  { value: "sheriff", label: "Шериф" },
  { value: "citizen", label: "Мирный" },
];

const field =
  "rounded-lg border border-ink-700 bg-ink-900 px-3.5 py-2.5 text-sm text-ink-50 focus:border-brand-500 focus:outline-none";
const label = "flex flex-col gap-1.5 text-xs font-medium text-ink-400";

export function PlayerForm({ player }: { player?: PlayerAdminOut }) {
  const router = useRouter();
  const isEdit = Boolean(player);

  const [nickname, setNickname] = useState(player?.nickname ?? "");
  const [slug, setSlug] = useState(player?.slug ?? "");
  // Отслеживает только ручную правку slug. Раньше в режиме редактирования флаг
  // сразу ставился в true и вместе со вторым условием в handleNicknameBlur
  // полностью выключал автоподбор -- при смене ника предложения не было.
  const [slugTouched, setSlugTouched] = useState(false);
  const [slugSuggestion, setSlugSuggestion] = useState<string | null>(null);
  const originalNickname = player?.nickname ?? "";
  const [fullName, setFullName] = useState(player?.full_name ?? "");
  const [age, setAge] = useState(player?.age?.toString() ?? "");
  const [favoriteRole, setFavoriteRole] = useState<InGameRole | "">(player?.favorite_role ?? "");
  const [experience, setExperience] = useState(player?.experience ?? "");
  const [bio, setBio] = useState(player?.bio ?? "");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [slugLoading, setSlugLoading] = useState(false);

  async function handleNicknameBlur() {
    setSlugSuggestion(null);
    if (slugTouched || !nickname.trim()) return;
    // При редактировании подбираем только если ник действительно поменяли.
    if (isEdit && nickname.trim() === originalNickname) return;

    setSlugLoading(true);
    try {
      const res = await clientFetch<{ slug: string }>(
        `/api/admin/players/slug-suggestion?nickname=${encodeURIComponent(nickname)}`
      );
      if (res.slug === slug) return;
      if (isEdit) {
        // Молча менять slug у существующего игрока нельзя: это его публичный
        // адрес, по нему уже могут быть ссылки. Показываем предложение, решает
        // администратор.
        setSlugSuggestion(res.slug);
      } else {
        setSlug(res.slug);
      }
    } catch {
      // ignore -- admin can still type the slug manually
    } finally {
      setSlugLoading(false);
    }
  }

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
          onBlur={handleNicknameBlur}
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
            setSlugTouched(true);
          }}
          placeholder={slugLoading ? "Подбираем…" : "chef"}
          pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]"
          required
        />
        {slugSuggestion && (
          <span className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-800 bg-brand-900/25 px-3 py-2 font-normal text-ink-200">
            Ник изменился. Предложение: <code className="font-mono text-ink-50">{slugSuggestion}</code>
            <button
              type="button"
              onClick={() => {
                setSlug(slugSuggestion);
                setSlugTouched(true);
                setSlugSuggestion(null);
              }}
              className="rounded-pill bg-brand-600 px-3 py-1 text-xs font-medium text-ink-50 hover:bg-brand-500"
            >
              Подставить
            </button>
            <button
              type="button"
              onClick={() => setSlugSuggestion(null)}
              className="rounded-pill border border-ink-700 px-3 py-1 text-xs text-ink-300 hover:border-ink-500"
            >
              Оставить как есть
            </button>
            <span className="w-full text-ink-500">
              Меняя slug, вы меняете адрес страницы игрока — старые ссылки перестанут работать.
            </span>
          </span>
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
