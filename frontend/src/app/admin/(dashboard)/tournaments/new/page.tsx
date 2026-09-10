import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { TournamentForm } from "@/components/admin/tournament-form";

export default function NewTournamentPage() {
  return (
    <div>
      <Link
        href="/admin/tournaments"
        className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100"
      >
        <ArrowLeft size={16} />
        Турниры
      </Link>
      <h1 className="mt-3 font-display text-2xl text-ink-50">Новый турнир</h1>
      <div className="mt-6">
        <TournamentForm />
      </div>
    </div>
  );
}
