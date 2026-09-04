import Link from "next/link";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { GameForm } from "@/components/admin/game-form";

export default function NewGamePage() {
  return (
    <div>
      <Link href="/mafia/admin/games" className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100">
        <ArrowLeft size={16} />
        Игры
      </Link>
      <h1 className="mt-3 font-display text-2xl text-ink-50">Новая игра</h1>
      <div className="mt-6">
        <GameForm />
      </div>
    </div>
  );
}
