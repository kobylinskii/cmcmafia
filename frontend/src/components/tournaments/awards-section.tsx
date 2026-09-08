import Link from "next/link";
import { Crown, Medal, Star } from "@phosphor-icons/react/dist/ssr";
import type { TournamentAwardOut } from "@/types/api";
import { PLACE_NOMINATIONS } from "@/types/api";
import { formatDash, formatPercent } from "@/lib/format";
import { PlayerAvatar } from "@/components/ui/player-avatar";

/**
 * Номинации и призёры турнира. Считаются по играм финального (или
 * единственного) стола -- backend/app/services/awards_service.py, там же
 * формулы. Блок появляется на публичной странице только после того, как админ
 * его опубликовал, поэтому пустой список здесь -- нормальное состояние, а не
 * ошибка загрузки.
 */
export function TournamentAwardsSection({
  awards,
  tableName,
}: {
  awards: TournamentAwardOut[];
  /** Название стола, по которому всё посчитано (null -- турнир без сеток). */
  tableName: string | null;
}) {
  if (awards.length === 0) return null;

  const places = awards.filter((a) => PLACE_NOMINATIONS.includes(a.nomination));
  const mvp = awards.find((a) => a.nomination === "mvp") ?? null;
  const roles = awards.filter(
    (a) => !PLACE_NOMINATIONS.includes(a.nomination) && a.nomination !== "mvp"
  );
  const scope = tableName ? `финального стола («${tableName}»)` : "турнира";

  return (
    <>
      {places.some((a) => a.winner) && (
        <section className="mt-10">
          <h2 className="font-display text-xl text-ink-50">Призёры</h2>
          <p className="mt-1 text-sm text-ink-500">Топ-3 по сумме баллов {scope}.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {places.map((award, i) => (
              <AwardCard key={award.nomination} award={award} accent={i === 0} />
            ))}
          </div>
        </section>
      )}

      {(mvp?.winner || roles.some((a) => a.winner)) && (
        <section className="mt-10">
          <h2 className="font-display text-xl text-ink-50">Номинации</h2>
          <p className="mt-1 text-sm text-ink-500">По играм {scope}.</p>
          {/* MVP -- главная номинация: во всю ширину и со своей статистикой,
              у ролевых карточек она короткая. */}
          <div className="mt-4 flex flex-col gap-3">
            {mvp?.winner && <AwardCard award={mvp} accent wide />}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {roles.map((award) => (
                <AwardCard key={award.nomination} award={award} />
              ))}
            </div>
          </div>
        </section>
      )}
    </>
  );
}

function AwardCard({
  award,
  accent = false,
  wide = false,
}: {
  award: TournamentAwardOut;
  accent?: boolean;
  /** Карточка во всю ширину секции -- статистика раскладывается в строку. */
  wide?: boolean;
}) {
  const { winner } = award;
  if (!winner) return null;

  const isPlace = PLACE_NOMINATIONS.includes(award.nomination);
  const isMvp = award.nomination === "mvp";
  // У ролевых номинаций строка статистики одна -- в две колонки подпись
  // «Игр в зачёте» переносилась бы посреди узкой карточки.
  const full = isPlace || isMvp;
  const Icon = award.nomination === "first_place" ? Crown : isPlace ? Medal : Star;

  return (
    <article
      className={`flex flex-col rounded-card border p-5 ${
        accent ? "border-brand-700/70 bg-brand-900/15" : "border-ink-800 bg-ink-900"
      }`}
    >
      <h3 className="flex items-center gap-2 text-sm font-medium text-ink-300">
        <Icon size={17} weight={accent ? "fill" : "regular"} className="text-brand-400" />
        {award.title}
      </h3>

      <Link
        href={`/mafia/${winner.slug}`}
        className="mt-3 flex items-center gap-3 font-display text-lg text-ink-50 hover:text-brand-300"
      >
        <PlayerAvatar photoUrl={winner.photo_url} nickname={winner.nickname} />
        {winner.nickname}
      </Link>

      <p className="mt-3 flex items-baseline gap-2">
        <span className="font-mono text-2xl text-ink-50">{formatDash(winner.score)}</span>
        {/* Подпись, а не «N баллов за игру»: число дробное, и согласовывать с
            ним существительное пришлось бы по падежу на каждое значение. */}
        <span className="text-xs text-ink-500">
          {isPlace ? "сумма баллов" : "средний доп. балл"}
        </span>
      </p>

      <dl
        className={`mt-4 grid gap-x-4 gap-y-1.5 border-t border-ink-800 pt-3 text-sm ${
          wide ? "grid-cols-2 sm:grid-cols-4" : full ? "grid-cols-2" : "grid-cols-1"
        }`}
      >
        <Stat label={isPlace ? "Игр на столе" : "Игр в зачёте"} value={winner.games_count} />
        {full && (
          <>
            <Stat label="Побед" value={winner.wins} />
            <Stat label="Поражений" value={winner.losses} />
            <Stat label="% побед" value={formatPercent(winner.win_rate)} />
            <Stat label="От судей" value={formatDash(winner.points_judge)} />
            <Stat label="ЛХ" value={formatDash(winner.lh_points)} />
            {isMvp && <Stat label="Итог в таблице" value={formatDash(winner.total_score)} />}
          </>
        )}
      </dl>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-ink-500">{label}</dt>
      <dd className="font-mono text-ink-200">{value}</dd>
    </div>
  );
}
