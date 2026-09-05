"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { clientFetch, ApiError } from "@/lib/api";
import type { TournamentAdminOut } from "@/types/api";
import { TournamentForm } from "@/components/admin/tournament-form";
import { TournamentStagesManager } from "@/components/admin/tournament-stages-manager";

export default function EditTournamentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [tournament, setTournament] = useState<TournamentAdminOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    clientFetch<TournamentAdminOut>(`/api/admin/tournaments/${id}`)
      .then(setTournament)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить"));
  }, [id]);

  return (
    <div>
      <Link
        href="/mafia/admin/tournaments"
        className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100"
      >
        <ArrowLeft size={16} />
        Турниры
      </Link>
      <h1 className="mt-3 font-display text-2xl text-ink-50">
        {tournament ? tournament.name : "Загрузка…"}
      </h1>
      {error && <p className="mt-4 text-sm text-brand-300">{error}</p>}
      {tournament && (
        <div className="mt-6 flex flex-col gap-10">
          <TournamentForm tournament={tournament} />
          <div className="border-t border-ink-800 pt-8">
            <TournamentStagesManager tournamentId={tournament.id} />
          </div>
        </div>
      )}
    </div>
  );
}
