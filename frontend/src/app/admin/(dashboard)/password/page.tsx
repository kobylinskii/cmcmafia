"use client";

import { useState } from "react";
import { CheckCircle } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api";
import { adminChangePassword } from "@/lib/admin-auth";
import { Button } from "@/components/ui/button";
import { fieldLarge as field, fieldLabelLg as label } from "@/lib/ui";

const MIN_LENGTH = 10;

export default function ChangePasswordPage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  // Проверяем на клиенте только то, что сервер физически не может знать
  // (совпадение с повтором), и длину -- чтобы не гонять заведомо плохой
  // пароль по сети. Всё остальное решает бэкенд.
  const tooShort = next.length > 0 && next.length < MIN_LENGTH;
  const mismatch = repeat.length > 0 && next !== repeat;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError("Новый пароль и его повтор не совпадают");
      return;
    }
    setLoading(true);
    try {
      await adminChangePassword(current, next);
      setDone(true);
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось сменить пароль");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-xl">
      <h1 className="font-display text-2xl text-ink-50">Смена пароля</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink-400">
        Здесь меняется пароль вашей учётной записи. Чтобы выдать или сбросить доступ
        другому человеку, откройте раздел «Игроки» и нажмите на ключ в его строке.
      </p>

      {done && (
        <p
          role="status"
          className="mt-6 flex items-start gap-2.5 rounded-card border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-200"
        >
          <CheckCircle size={18} weight="duotone" className="mt-px shrink-0 text-brand-400" />
          Пароль изменён. Вы остались в системе, но на других устройствах вход нужно будет
          выполнить заново — с новым паролем.
        </p>
      )}

      <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-5">
        <label className={label}>
          Текущий пароль
          <input
            type="password"
            className={field}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <label className={label}>
          Новый пароль
          <input
            type="password"
            className={field}
            value={next}
            onChange={(e) => {
              setNext(e.target.value);
              setDone(false);
            }}
            autoComplete="new-password"
            minLength={MIN_LENGTH}
            required
            aria-invalid={tooShort || undefined}
          />
          <span className={tooShort ? "font-normal text-brand-300" : "font-normal text-ink-500"}>
            Не короче {MIN_LENGTH} символов.
          </span>
        </label>

        <label className={label}>
          Повторите новый пароль
          <input
            type="password"
            className={field}
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            autoComplete="new-password"
            required
            aria-invalid={mismatch || undefined}
          />
          {mismatch && <span className="font-normal text-brand-300">Пароли не совпадают.</span>}
        </label>

        {error && (
          <p
            role="alert"
            className="rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200"
          >
            {error}
          </p>
        )}

        <div>
          <Button type="submit" disabled={loading || tooShort || mismatch || !current || !next}>
            {loading ? "Меняем…" : "Сменить пароль"}
          </Button>
        </div>
      </form>
    </div>
  );
}
