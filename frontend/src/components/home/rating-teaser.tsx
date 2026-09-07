import { Container } from "@/components/ui/container";
import { FormulaLink } from "@/components/home/formula-link";
import { Reveal } from "@/components/reveal";

export function RatingTeaser() {
  return (
    <section className="py-20 md:py-28">
      <Container className="max-w-3xl">
        <Reveal>
          <h2 className="font-display text-2xl font-medium text-ink-50 md:text-3xl">
            Рейтинг по системе Эло
          </h2>
          <p className="mt-4 text-base leading-relaxed text-ink-300 md:text-lg">
            Рейтинг меняется после каждой партии — от баллов за игру и силы стола.
            Победа над сильными соперниками стоит дороже. Первые тридцать игр
            новичка идут с повышенным коэффициентом.
          </p>
          <div className="mt-6">
            <FormulaLink />
          </div>
        </Reveal>
      </Container>
    </section>
  );
}
