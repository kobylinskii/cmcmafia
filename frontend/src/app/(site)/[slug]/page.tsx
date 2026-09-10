import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Trophy, Cake, IdentificationCard, Skull } from "@phosphor-icons/react/dist/ssr";
import { ApiError, mediaUrl } from "@/lib/api";
import { serverGet } from "@/lib/api-server";
import type { GameListOut, PlayerDetailOut } from "@/types/api";
import { ROLE_LABELS } from "@/types/api";
import { Container } from "@/components/ui/container";
import { Badge } from "@/components/ui/badge";
import { StatTile } from "@/components/player/stat-tile";
import { RoleCard } from "@/components/player/role-card";
import { LhDistribution } from "@/components/player/lh-distribution";
import { PlayerGamesFilterBar } from "@/components/player/player-games-filter-bar";
import { GameCard } from "@/components/games/game-card";
import { formatPercent, formatDash, formatNumber, plural, withCount } from "@/lib/format";
import { firstParam, intParam } from "@/lib/search-params";

// Рендер на каждый запрос, а не пререндер при сборке. Кеширование живёт
// уровнем ниже -- в serverGet, где у каждого запроса к API стоит
// next: { revalidate, tags } (см. lib/api-server.ts), и сбрасывается по тегу
// после правки в админке. Страничного revalidate здесь быть не должно: Next
// тогда пытается собрать страницу статически в момент `docker compose build`,
// где бэкенда ещё нет, и сборка падает на getaddrinfo ENOTFOUND api.
export const dynamic = "force-dynamic";

async function getPlayer(slug: string): Promise<PlayerDetailOut | null> {
  try {
    return await serverGet<PlayerDetailOut>(`/api/players/${encodeURIComponent(slug)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function generateMetadata({ params }: PageProps<"/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const data = await getPlayer(slug);
  return { title: data ? data.player.nickname : "Игрок не найден" };
}

export default async function PlayerPage({ params, searchParams }: PageProps<"/[slug]">) {
  const { slug } = await params;
  const data = await getPlayer(slug);
  if (!data) notFound();

  const { player, stats } = data;
  const photo = mediaUrl(player.photo_url);
  const hasFirstKills = stats.first_kill_count > 0;

  const sp = await searchParams;
  // "all" -- отдельный режим фильтра «показать все»; всё остальное приводится
  // к допустимому диапазону, иначе мусор в URL ронял страницу в 500.
  const rawLimit = firstParam(sp, "glimit") ?? "10";
  const isAll = rawLimit === "all";
  const glimit = isAll ? "all" : String(intParam(sp, "glimit", { def: 10, min: 1, max: 100 }));
  const gamesLimit = isAll ? 500 : Number(glimit);
  const gamesOffset = isAll ? 0 : intParam(sp, "goffset", { def: 0, min: 0, max: 100_000 });

  const games = await serverGet<GameListOut>("/api/games", {
    player_slug: slug,
    limit: gamesLimit,
    offset: gamesOffset,
  });

  const buildGamesUrl = (nextOffset: number) => {
    const p = new URLSearchParams();
    p.set("glimit", glimit);
    p.set("goffset", String(nextOffset));
    return `/${slug}?${p.toString()}#games`;
  };

  return (
    <Container className="py-14">
      {/* На узком экране фото, ник, имя и плашки идут колонкой по центру:
          слева они висели у края с большим пустым полем справа. С sm блок
          возвращается в строку и выравнивание по левому краю. */}
      <div className="flex flex-col items-center gap-8 text-center sm:flex-row sm:items-start sm:text-left">
        <div className="relative h-32 w-32 shrink-0 overflow-hidden rounded-card border border-ink-800 bg-ink-900 sm:h-40 sm:w-40">
          {photo ? (
            <Image
              src={photo}
              alt={player.nickname}
              fill
              sizes="(min-width: 640px) 160px, 128px"
              // Оптимизатор Next пережимает фото ВТОРОЙ раз после нашего же
              // JPEG (backend/app/services/player_service.py), и на дефолтных
              // 75 лицо в карточке заметно мылится. 90 стоит десяток лишних
              // килобайт на одну картинку страницы. Значение обязано быть в
              // images.qualities -- иначе Next 16 округлит его к ближайшему
              // разрешённому, то есть молча вернёт те же 75.
              quality={90}
              className="object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center font-display text-4xl text-ink-600">
              {player.nickname.slice(0, 1).toUpperCase()}
            </div>
          )}
        </div>

        <div className="w-full flex-1">
          <h1 className="font-display text-3xl font-medium text-ink-50 md:text-4xl">{player.nickname}</h1>
          {player.full_name && <p className="mt-1 text-ink-400">{player.full_name}</p>}

          <div className="mt-4 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
            {player.favorite_role && (
              <Badge tone="brand">
                <Trophy size={13} className="mr-1.5" />
                Любимая роль: {ROLE_LABELS[player.favorite_role]}
              </Badge>
            )}
            {player.age && (
              <Badge tone="outline">
                <Cake size={13} className="mr-1.5" />
                {withCount(player.age, ["год", "года", "лет"])}
              </Badge>
            )}
            {player.experience && (
              <Badge tone="outline">
                <IdentificationCard size={13} className="mr-1.5" />
                {player.experience}
              </Badge>
            )}
          </div>

          {player.bio && <p className="prose-measure mt-5 text-base leading-relaxed text-ink-300">{player.bio}</p>}
        </div>
      </div>

      <section className="mt-12">
        <h2 className="font-display text-xl text-ink-50">Общая статистика</h2>
        <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-7">
          <StatTile label="Игр" value={stats.total_games} />
          <StatTile label="Побед" value={stats.wins} />
          <StatTile label="Поражений" value={stats.losses} />
          <StatTile label="Ничьих" value={stats.draws} />
          <StatTile label="% побед" value={formatPercent(stats.win_rate)} />
          <StatTile label="Средний балл" value={formatDash(stats.avg_score)} />
          {/* Плиток семь, а колонок два (мобильный) и четыре (md) -- последняя
              оставалась одна в ряду, и рядом зияла дыра. Растягиваем её на
              остаток ряда; на lg колонок семь и растягивать нечего. */}
          <StatTile
            label="Средний доп. балл"
            value={formatDash(stats.avg_bonus)}
            className="col-span-2 lg:col-span-1"
          />
        </div>
        {stats.rating !== null && (
          <div className="mt-4 grid grid-cols-2 gap-4 sm:max-w-lg">
            <StatTile
              label="Текущий рейтинг"
              value={Math.round(stats.rating)}
              // Дательный падеж: «по 1 рейтинговой игре», «по 2 рейтинговым играм».
              sub={`по ${formatNumber(stats.rating_games_count)} ${plural(
                stats.rating_games_count,
                ["рейтинговой игре", "рейтинговым играм", "рейтинговым играм"]
              )}`}
            />
            {stats.rank !== null && <StatTile label="Место в рейтинге" value={`#${stats.rank}`} />}
          </div>
        )}
      </section>

      <section className="mt-10">
        <h2 className="font-display text-xl text-ink-50">По картам и ролям</h2>
        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <RoleCard label="Чёрная карта" games={stats.black_card_games} winRate={stats.black_card_win_rate} tone="black" />
          <RoleCard label="Красная карта" games={stats.red_card_games} winRate={stats.red_card_win_rate} tone="red" />
          <RoleCard label="Дон" games={stats.don_games} winRate={stats.don_win_rate} tone="black" />
          <RoleCard label="Шериф" games={stats.sheriff_games} winRate={stats.sheriff_win_rate} tone="red" />
        </div>
      </section>

      <section className="mt-10">
        <h2 className="flex items-center gap-2 font-display text-xl text-ink-50">
          <Skull size={20} className="text-brand-400" />
          Первоубиенный
        </h2>
        <p className="mt-3 text-base text-ink-300">
          Убит первым: <span className="font-mono text-ink-50">{stats.first_kill_count}</span>{" "}
          {plural(stats.first_kill_count, ["раз", "раза", "раз"])}
          {stats.total_games > 0 && ` из ${stats.total_games}`}.
        </p>
        {hasFirstKills && (
          <div className="mt-5 max-w-xl">
            <p className="mb-3 text-xs text-ink-500">Лучший ход: сколько чёрных названо из трёх</p>
            <LhDistribution distribution={stats.lh_distribution} />
          </div>
        )}
      </section>

      <section id="games" className="mt-10 scroll-mt-20">
        <h2 className="font-display text-xl text-ink-50">Игры игрока</h2>

        <div className="mt-4">
          <PlayerGamesFilterBar />
        </div>

        <div className="mt-4 flex flex-col gap-3">
          {games.items.length === 0 && (
            <p className="rounded-card border border-ink-800 bg-ink-900 p-8 text-center text-ink-400">
              Пока нет сыгранных игр.
            </p>
          )}
          {games.items.map((game) => (
            <GameCard key={game.id} game={game} />
          ))}
        </div>

        {!isAll && games.total > gamesLimit && (
          <div className="mt-8 flex items-center justify-between text-sm text-ink-300">
            <Link
              href={buildGamesUrl(Math.max(0, gamesOffset - gamesLimit))}
              aria-disabled={gamesOffset === 0}
              className={gamesOffset === 0 ? "pointer-events-none opacity-30" : "hover:text-ink-50"}
            >
              ← Новее
            </Link>
            <span className="text-ink-500">
              {gamesOffset + 1}-{Math.min(gamesOffset + gamesLimit, games.total)} из {games.total}
            </span>
            <Link
              href={buildGamesUrl(gamesOffset + gamesLimit)}
              aria-disabled={gamesOffset + gamesLimit >= games.total}
              className={gamesOffset + gamesLimit >= games.total ? "pointer-events-none opacity-30" : "hover:text-ink-50"}
            >
              Старее →
            </Link>
          </div>
        )}
      </section>
    </Container>
  );
}
