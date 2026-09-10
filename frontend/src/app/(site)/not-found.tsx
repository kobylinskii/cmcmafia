import { LogoMark } from "@/components/logo";
import { LinkButton } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6 px-4 text-center">
      {/* Крупнее прежних 96px: на пустой странице логотип -- единственный
          якорь, и в прежнем размере он терялся в пустоте. */}
      <LogoMark size={180} className="max-w-[45vw]" />
      <div>
        <h1 className="font-display text-2xl text-ink-50 md:text-3xl">Страница не найдена</h1>
        <p className="mt-2 text-base text-ink-400">Такой игры, игрока или раздела здесь нет.</p>
      </div>
      <LinkButton href="/">На главную</LinkButton>
    </div>
  );
}
