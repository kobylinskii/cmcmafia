import Link from "next/link";
import { ArrowUpRight, ListChecks, Trophy } from "@phosphor-icons/react/dist/ssr";
import { Container } from "@/components/ui/container";
import { Reveal } from "@/components/reveal";

const cards = [
  {
    href: "/mafia/games",
    icon: ListChecks,
    title: "Игры",
    body: "Полная таблица каждой сыгранной партии: состав, роли, баллы и исход.",
    tone: "large" as const,
  },
  {
    href: "/mafia/rating",
    icon: Trophy,
    title: "Рейтинг",
    body: "Таблица клуба по системе Эло и поиск конкретного игрока.",
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
        <div className="mt-8 grid grid-cols-1 gap-5 lg:grid-cols-5">
          {cards.map((card, i) => (
            <Reveal
              key={card.href}
              delay={i * 0.1}
              className={card.tone === "large" ? "lg:col-span-3" : "lg:col-span-2"}
            >
              <Link
                href={card.href}
                className="group flex h-full flex-col justify-between rounded-card border border-ink-800 bg-ink-900 p-8 transition-colors hover:border-brand-600/60"
              >
                <div>
                  <card.icon size={28} weight="duotone" className="text-brand-400" />
                  <h3 className="mt-5 font-display text-xl text-ink-50">{card.title}</h3>
                  <p className="mt-2 max-w-sm text-sm leading-relaxed text-ink-300">{card.body}</p>
                </div>
                <span className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-ink-200 group-hover:text-brand-400">
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
