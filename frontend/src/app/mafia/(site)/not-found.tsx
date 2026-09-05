import { LogoMark } from "@/components/logo";
import { LinkButton } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6 px-4 text-center">
      <LogoMark size={96} />
      <div>
        <h1 className="font-display text-2xl text-ink-50">Страница не найдена</h1>
        <p className="mt-2 text-sm text-ink-400">Такой игры, игрока или раздела здесь нет.</p>
      </div>
      <LinkButton href="/mafia">На главную</LinkButton>
    </div>
  );
}
