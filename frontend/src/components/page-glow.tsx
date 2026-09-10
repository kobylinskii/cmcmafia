/**
 * Shared ambient background for every /* page (design-taste-frontend
 * skill 4.11, page theme lock -- one dark theme, consistent surface
 * treatment everywhere, not just the homepage hero). Fixed + pointer-events
 * none per skill 6.E so it never costs scroll-repaint.
 */
export function PageGlow() {
  return (
    <div aria-hidden className="page-glow pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      {/* Тёплый очаг из правого верхнего угла -- как подсветка над игровым
          столом. Спускается по диагонали и сходит на нет к середине экрана,
          где идут таблицы и абзацы: свечение под текстом осветляет фон и
          роняет контраст подписей. */}
      <div className="page-glow-core" />
      {/* Плотнее прежнего (было 700/20, 800/20, 600/15) и крупнее, но по краям:
          середина, где идут таблицы и абзацы, остаётся самым тёмным местом.
          На мобильной ширине пятна шире самого экрана, поэтому там они
          уменьшены и подняты -- иначе красное заливает и полосы чтения, и
          «немного больше градиента» превращается в сплошной бордовый фон. */}
      <div className="absolute -top-28 right-[-18%] h-[300px] w-[340px] rounded-full bg-brand-600/28 blur-[90px] md:-top-44 md:right-[-7%] md:h-[540px] md:w-[580px] md:blur-[125px]" />
      <div className="absolute top-[28%] -left-28 hidden h-[400px] w-[400px] rounded-full bg-brand-700/22 blur-[115px] md:top-[32%] md:-left-36 md:block" />
      <div className="absolute bottom-[-12%] right-[8%] h-[260px] w-[280px] rounded-full bg-brand-700/20 blur-[100px] md:bottom-[-18%] md:right-[15%] md:h-[450px] md:w-[480px] md:blur-[145px]" />
    </div>
  );
}
