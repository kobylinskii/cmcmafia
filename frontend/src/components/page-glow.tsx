/**
 * Shared ambient background for every /mafia/* page (design-taste-frontend
 * skill 4.11, page theme lock -- one dark theme, consistent surface
 * treatment everywhere, not just the homepage hero). Fixed + pointer-events
 * none per skill 6.E so it never costs scroll-repaint.
 */
export function PageGlow() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute -top-40 right-[-8%] h-[520px] w-[520px] rounded-full bg-brand-700/20 blur-[130px]" />
      <div className="absolute top-[38%] -left-32 h-[380px] w-[380px] rounded-full bg-brand-800/20 blur-[110px]" />
      <div className="absolute bottom-[-15%] right-[18%] h-[440px] w-[440px] rounded-full bg-brand-600/15 blur-[140px]" />
    </div>
  );
}
