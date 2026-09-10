"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LogoMark } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { adminLogin } from "@/lib/admin-auth";
import { ApiError } from "@/lib/api";
import { safeNextPath } from "@/lib/search-params";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await adminLogin(username, password);
      const next = safeNextPath(searchParams.get("next"));
      router.push(next);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось войти");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-ui flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-3 text-center">
          <LogoMark size={80} priority />
          <h1 className="font-display text-xl text-ink-50">Админка клуба</h1>
        </div>

        <form onSubmit={handleSubmit} className="mt-8 flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm text-ink-300">
            Логин
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              className="rounded-lg border border-ink-700 bg-ink-900 px-4 py-2.5 text-ink-50 focus:border-brand-500 focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm text-ink-300">
            Пароль
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="rounded-lg border border-ink-700 bg-ink-900 px-4 py-2.5 text-ink-50 focus:border-brand-500 focus:outline-none"
            />
          </label>

          {error && (
            <p role="alert" className="rounded-lg border border-brand-800 bg-brand-900/30 px-4 py-2.5 text-sm text-brand-200">
              {error}
            </p>
          )}

          <Button type="submit" disabled={loading} className="mt-2 w-full">
            {loading ? "Входим…" : "Войти"}
          </Button>
        </form>
      </div>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
