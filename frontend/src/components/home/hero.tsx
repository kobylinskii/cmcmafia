import { LinkButton } from "@/components/ui/button";
import { LogoBadge } from "@/components/logo";

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-16 pb-20 md:pt-24 md:pb-28">
      <div
        aria-hidden
        className="brand-glow pointer-events-none absolute -top-36 right-[-10%] h-[580px] w-[600px] rounded-full bg-brand-600/32 blur-[125px]"
      />
      <div className="mx-auto grid w-full max-w-7xl grid-cols-1 items-center gap-12 px-4 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:px-8">
        <div className="relative z-10 flex flex-col items-start gap-6">
          <h1 className="font-display text-4xl leading-[1.08] font-medium text-ink-50 md:text-6xl">
            Вся статистика <span className="text-brand-400">клуба</span>.
          </h1>
          <p className="max-w-md text-base leading-relaxed text-ink-300 md:text-lg">
            Мы клуб спортивной мафии для всех студентов МГУ. А также скоро сможем приглашать гостей.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <LinkButton href="/games">Смотреть игры</LinkButton>
            <LinkButton href="/rating" variant="secondary">
              Рейтинг клуба
            </LinkButton>
          </div>
        </div>

        <div className="relative mx-auto w-full max-w-md lg:max-w-lg">
          <div
            aria-hidden
            className="brand-glow absolute inset-0 -z-10 scale-90 rounded-full bg-brand-600/30 blur-[100px]"
          />
          {/* hero-badge: в светлой теме красный ореол под знаком снимается --
              на бумаге он не «подсвечивает» эмблему, а моет её контуры. */}
          <LogoBadge className="hero-badge w-full drop-shadow-[0_20px_60px_rgba(181,41,35,0.35)]" priority />
        </div>
      </div>
    </section>
  );
}
