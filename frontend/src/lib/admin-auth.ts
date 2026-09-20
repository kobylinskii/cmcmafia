import { clientFetch } from "@/lib/api";
import type { LoginOut } from "@/types/api";

export function adminLogin(username: string, password: string) {
  return clientFetch<LoginOut>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function adminLogout() {
  return clientFetch<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
}

export function adminMe() {
  return clientFetch<LoginOut>("/api/auth/me");
}

/** Убрать игры, которых больше нигде не видно: слот «оцениваться не будет»,
 * время которого прошло. Фоновых задач у API нет намеренно, поэтому уборку
 * запускает вход в админку -- см. backend/app/routers/admin_schedule.py. */
export function adminCleanupSchedule() {
  return clientFetch<{ deleted: number }>("/api/admin/schedule/cleanup", { method: "POST" });
}

export function adminChangePassword(currentPassword: string, newPassword: string) {
  return clientFetch<{ ok: boolean }>("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}
