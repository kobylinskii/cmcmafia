import { Info } from "@phosphor-icons/react/dist/ssr";
import type { RatingFormulaOut } from "@/types/api";
import { Badge } from "@/components/ui/badge";

/**
 * Описание формулы рейтинга. Раньше это был один <p> с сырым текстом от
 * бэкенда (whitespace-pre-line) -- формула тонула в сплошном абзаце тем же
 * кеглем, что и обычная проза, а три строки коэффициентов формата читались
 * как ещё один абзац, а не как таблица. Теперь бэкенд отдаёт структуру
 * (RatingFormulaOut), и каждая часть верстается тем, чем должна быть:
 * формула -- крупным моноширинным блоком, обозначения -- списком терминов,
 * коэффициенты -- настоящими таблицами.
 */
export function RatingFormula({ formula }: { formula: RatingFormulaOut }) {
  return (
    <section className="mt-14">
      <h2 className="font-display text-2xl font-medium text-ink-50 md:text-3xl">
        Как считается рейтинг
      </h2>
      <p className="prose-measure mt-3 text-base leading-relaxed text-ink-300">
        {formula.intro} Старт: {formula.start_rating} очков. За каждую сыгранную
        рейтинговую игру рейтинг меняется по формуле:
      </p>

      {/* Формула -- главный визуальный акцент блока: крупно, моноширинным
          шрифтом, в отдельной панели, а не растворена в тексте абзаца. */}
      <div className="mt-6 overflow-x-auto rounded-card border border-ink-800 bg-ink-900 px-6 py-8 text-center">
        <p className="whitespace-nowrap font-mono text-2xl tracking-wide text-ink-50 sm:text-3xl">
          {formula.formula}
        </p>
      </div>

      <dl className="mt-6 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
        {formula.legend.map((item) => (
          <div key={item.symbol} className="flex items-baseline gap-3">
            <dt className="shrink-0 rounded-lg bg-ink-800 px-2 py-0.5 font-mono text-sm text-brand-300">
              {item.symbol}
            </dt>
            <dd className="text-sm leading-relaxed text-ink-300">{item.text}</dd>
          </div>
        ))}
      </dl>

      <p className="prose-measure mt-6 flex items-start gap-2.5 text-sm leading-relaxed text-ink-400">
        <Info size={18} className="mt-0.5 shrink-0 text-ink-500" />
        {formula.note}
      </p>

      <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-medium tracking-wide text-ink-400 uppercase">
            Коэффициент и штрафы по опыту
          </h3>
          <div className="mt-3 overflow-x-auto rounded-card border border-ink-800">
            <table aria-label="Коэффициент K и штрафы по опыту игрока" className="w-full min-w-[420px] border-collapse">
              <thead>
                <tr className="border-b border-ink-800 bg-ink-900 text-left text-xs font-medium text-ink-400">
                  <th scope="col" className="px-4 py-2.5">Опыт игрока</th>
                  <th scope="col" className="px-4 py-2.5 text-right">K</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Удаление</th>
                  <th scope="col" className="px-4 py-2.5 text-right">ППК</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {formula.k_tiers.map((tier) => (
                  <tr key={tier.condition} className="odd:bg-ink-900/40">
                    <td className="px-4 py-2.5 text-sm text-ink-100">{tier.condition}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm text-ink-50">{tier.k}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm text-ink-300">
                      −{tier.removal_penalty}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm text-ink-300">
                      −{tier.ppk_penalty}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-medium tracking-wide text-ink-400 uppercase">
            Вес формата игры
          </h3>
          <ul className="mt-3 flex flex-col gap-2">
            {formula.game_type_weights.map((w) => (
              <li
                key={w.game_type}
                className="flex items-center justify-between gap-3 rounded-card border border-ink-800 bg-ink-900 px-4 py-3"
              >
                <span className="text-sm text-ink-100">{w.label}</span>
                <span className="flex items-center gap-2">
                  {!w.rated && (
                    <Badge tone="outline" className="text-ink-400">
                      не влияет на рейтинг
                    </Badge>
                  )}
                  <span className="font-mono text-base text-ink-50">×{w.weight}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-sm leading-relaxed text-ink-500">{formula.training_note}</p>
        </div>
      </div>
    </section>
  );
}
