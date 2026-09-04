import { LinkButton } from "@/components/ui/button";
import { LogoBadge } from "@/components/logo";

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-16 pb-20 md:pt-24 md:pb-28">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 right-[-10%] h-[560px] w-[560px] rounded-full bg-brand-700/25 blur-[120px]"
      />
      <div className="mx-auto grid w-full max-w-7xl grid-cols-1 items-center gap-12 px-4 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:px-8">
        <div className="relative z-10 flex flex-col items-start gap-6">
          <h1 className="font-display text-4xl leading-[1.08] font-medium text-ink-50 md:text-6xl">
            Статистика <span className="text-brand-400">без прикрас</span>.
          </h1>
          <p className="max-w-md text-base leading-relaxed text-ink-300 md:text-lg">
            Результаты каждой сыгранной партии, рейтинг по системе Эло и профиль
            каждого игрока клуба.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <LinkButton href="/mafia/games">Смотреть игры</LinkButton>
            <LinkButton href="/mafia/rating" variant="secondary">
              Рейтинг клуба
            </LinkButton>
          </div>
        </div>

        <div className="relative mx-auto w-full max-w-md lg:max-w-lg">
          <div
            aria-hidden
            className="absolute inset-0 -z-10 scale-90 rounded-full bg-brand-600/25 blur-[100px]"
          />
          <LogoBadge className="w-full drop-shadow-[0_20px_60px_rgba(181,41,35,0.35)]" priority />
        </div>
      </div>
    </section>
  );
}
