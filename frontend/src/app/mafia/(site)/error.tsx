"use client";

import { LogoMark } from "@/components/logo";
import { Button } from "@/components/ui/button";

export default function SiteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6 px-4 text-center">
      <LogoMark size={64} />
      <div>
        <h1 className="font-display text-2xl text-ink-50">Что-то пошло не так</h1>
        <p className="mt-2 max-w-sm text-sm text-ink-400">
          Не удалось загрузить страницу. Обычно это временно — попробуйте ещё раз.
        </p>
      </div>
      <Button onClick={() => reset()}>Обновить</Button>
    </div>
  );
}
