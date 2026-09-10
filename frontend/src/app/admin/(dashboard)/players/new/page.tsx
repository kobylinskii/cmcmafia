import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { PlayerForm } from "@/components/admin/player-form";

export default function NewPlayerPage() {
  return (
    <div>
      <Link href="/admin/players" className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100">
        <ArrowLeft size={16} />
        Игроки
      </Link>
      <h1 className="mt-3 font-display text-2xl text-ink-50">Новый игрок</h1>
      <div className="mt-6">
        <PlayerForm />
      </div>
    </div>
  );
}
