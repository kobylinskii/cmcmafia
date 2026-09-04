import { Container } from "@/components/ui/container";
import { LinkButton } from "@/components/ui/button";
import { Reveal } from "@/components/reveal";

export function RatingTeaser() {
  return (
    <section className="py-20 md:py-28">
      <Container className="max-w-3xl">
        <Reveal>
          <h2 className="font-display text-2xl font-medium text-ink-50 md:text-3xl">
            Рейтинг считается по системе Эло
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-300 md:text-lg">
            Каждая партия меняет рейтинг игрока в зависимости от баллов за игру и
            силы стола: победа над более сильными соперниками стоит дороже. Новички
            в первые тридцать игр набирают и теряют очки быстрее.
          </p>
          <div className="mt-6">
            <LinkButton href="/mafia/rating" variant="secondary">
              Подробнее о формуле
            </LinkButton>
          </div>
        </Reveal>
      </Container>
    </section>
  );
}
