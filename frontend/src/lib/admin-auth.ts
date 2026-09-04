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
