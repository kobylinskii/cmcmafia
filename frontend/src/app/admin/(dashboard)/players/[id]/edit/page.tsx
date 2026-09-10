"use client";

import Link from "next/link";
import Image from "next/image";
import { use, useRef, useState } from "react";
import { ArrowLeft, UploadSimple } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError, mediaUrl } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import type { PlayerAdminOut } from "@/types/api";
import { PlayerForm } from "@/components/admin/player-form";

export default function EditPlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: player, error, setData: setPlayer } = useResource<PlayerAdminOut>(
    `/api/admin/players/${id}`
  );

  return (
    <div>
      <Link href="/admin/players" className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100">
        <ArrowLeft size={16} />
        Игроки
      </Link>
      <h1 className="mt-3 font-display text-2xl text-ink-50">{player ? player.nickname : "Загрузка…"}</h1>

      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}

      {player && (
        <div className="mt-6 flex flex-col gap-8 lg:flex-row">
          <PhotoUploader player={player} onUpdated={(url) => setPlayer({ ...player, photo_url: url })} />
          <PlayerForm player={player} />
        </div>
      )}
    </div>
  );
}

function PhotoUploader({ player, onUpdated }: { player: PlayerAdminOut; onUpdated: (url: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const photo = mediaUrl(player.photo_url);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await clientFetch<{ photo_url: string }>(`/api/admin/players/${player.id}/photo`, {
        method: "POST",
        body: form,
      });
      onUpdated(res.photo_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить фото");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="shrink-0">
      <div className="relative h-40 w-40 overflow-hidden rounded-card border border-ink-800 bg-ink-900">
        {photo ? (
          <Image
            src={photo}
            alt={player.nickname}
            fill
            // Блок ровно 160px (h-40), а стояло 128 -- браузер брал кандидат
            // мельче, чем рисует. Качество -- как на публичной странице игрока:
            // дефолтные 75 заметно мылят уже пережатый нами JPEG.
            sizes="160px"
            quality={90}
            className="object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-4xl text-ink-700">
            {player.nickname.slice(0, 1).toUpperCase()}
          </div>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Сбрасываем value сразу после чтения, а не полагаемся на то, что
          // React сделает это сам: браузер не генерирует change повторно,
          // если выбрать тот же файл ещё раз (путь в файловой системе не
          // изменился). Без сброса повторная загрузка того же снимка -- в том
          // числе сразу после ошибки, когда админ просто нажимает ту же
          // кнопку с тем же файлом -- визуально не делает вообще ничего.
          e.target.value = "";
          if (file) handleFile(file);
        }}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-pill border border-ink-700 px-4 py-2 text-xs font-medium text-ink-200 hover:border-ink-500 disabled:opacity-50"
      >
        <UploadSimple size={14} />
        {uploading ? "Загружаем…" : "Загрузить фото"}
      </button>
      {error && <p className="mt-2 text-xs text-brand-300">{error}</p>}
    </div>
  );
}
