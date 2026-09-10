import Link from "next/link";
import { ArrowUpRight, ChartLineUp, ListChecks, Trophy } from "@phosphor-icons/react/dist/ssr";
import { Container } from "@/components/ui/container";
import { Reveal } from "@/components/reveal";

const cards = [
  {
    href: "/rating",
    icon: ChartLineUp,
    title: "Рейтинг",
    body: "Таблица клуба по системе Эло. Разбор формулы и поиск игроков.",
    tone: "large" as const,
  },
  {
    href: "/tournaments",
    icon: Trophy,
    title: "Турниры",
    body: "Составы, площадки и таблицы по каждому турниру.",
    tone: "compact" as const,
  },
  {
    href: "/games",
    icon: ListChecks,
    title: "Игры",
    body: "Состав, роли и баллы каждой сыгранной партии.",
    tone: "compact" as const,
  },
];

export function ExploreSection() {
  return (
    <section className="py-20 md:py-28">
      <Container>
        <Reveal>
          <h2 className="font-display text-2xl font-medium text-ink-50 md:text-3xl">Что внутри</h2>
        </Reveal>
        {/* Асимметричная сетка (2fr/1fr/1fr), а не три равные колонки: рейтинг --
            главная страница клуба, за ней приходят чаще всего, и она открывает
            блок крупной карточкой. Турниры и игры -- входы поменьше. */}
        <div className="mt-8 grid grid-cols-1 gap-5 lg:grid-cols-[2fr_1fr_1fr]">
          {cards.map((card, i) => (
            <Reveal key={card.href} delay={i * 0.1}>
              <Link
                href={card.href}
                className="group flex h-full flex-col justify-between rounded-card border border-ink-800 bg-ink-900 p-8 transition-colors hover:border-brand-600/60"
              >
                <div>
                  <card.icon
                    size={card.tone === "large" ? 32 : 28}
                    weight="duotone"
                    className="text-brand-400"
                  />
                  <h3
                    className={
                      card.tone === "large"
                        ? "mt-5 font-display text-2xl text-ink-50"
                        : "mt-5 font-display text-xl text-ink-50"
                    }
                  >
                    {card.title}
                  </h3>
                  <p className="mt-2 max-w-sm text-base leading-relaxed text-ink-300">{card.body}</p>
                </div>
                <span className="mt-6 inline-flex items-center gap-1 text-base font-medium text-ink-200 group-hover:text-brand-400">
                  Открыть
                  <ArrowUpRight size={16} className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </span>
              </Link>
            </Reveal>
          ))}
        </div>
      </Container>
    </section>
  );
}
