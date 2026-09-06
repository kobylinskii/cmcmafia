from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.services import rating_service, visibility
from app.timeutil import CLUB_TZ

# ЛХ хранится в game_participants.lh как ПОПАДАНИЯ («сколько из трёх названных
# оказались чёрными»), в клубной записи 0 / 0.5 / 1 / 1.5 == 0/3, 1/3, 2/3, 3/3.
# Баллы за них начисляются иначе: 0/3 и 1/3 не дают ничего, 2/3 -> 0.5 балла,
# 3/3 -> 1 балл. Отсюда и путаница «в поле стоит 0, это 0/3 или 1/3?»: данные
# эти случаи различают, а вот подписи в интерфейсе называли попадания баллами.
# Зеркалит rating_service.LH_POINTS -- держать в синхроне.
_LH_POINTS_SQL = case(
    (models.GameParticipant.lh == 1.5, 1.0),
    (models.GameParticipant.lh == 1.0, 0.5),
    else_=0.0,
)

# Штрафы в ИГРОВЫХ баллах. ЖК и СК уже хранятся как баллы, а удаления и ППК --
# как счётчик и флаг, поэтому им нужны ставки. Это не то же самое, что штрафы
# в очках Эло (rating_service._penalty_rates, там 3..15 очков рейтинга).
#
# Ставка за ППК -- 2.5 балла, по регламенту клуба. Ставка за удаление
# регламентом не подтверждена и остаётся допущением. Меняются здесь, в одном
# месте, и пересчёта БД не требуют.
SCORE_PENALTY_PER_REMOVAL = 0.5
SCORE_PENALTY_PPK = 2.5

_PENALTY_SQL = (
    func.coalesce(models.GameParticipant.zk, 0)
    + func.coalesce(models.GameParticipant.sk, 0)
    + func.coalesce(models.GameParticipant.removals, 0) * SCORE_PENALTY_PER_REMOVAL
    + case((models.GameParticipant.ppk.is_(True), SCORE_PENALTY_PPK), else_=0.0)
)

# Средний балл -- все баллы за игру минус все штрафы.
_SCORE_SQL = (
    models.GameParticipant.points_win
    + models.GameParticipant.points_judge
    + _LH_POINTS_SQL
    + func.coalesce(models.GameParticipant.ci, 0)
    - _PENALTY_SQL
)

# Средний дополнительный балл -- только судейские и ЛХ. Ci сюда НЕ входит:
# это компенсация, а не заработанный игроком дополнительный балл.
_BONUS_SQL = models.GameParticipant.points_judge + _LH_POINTS_SQL

BLACK_ROLES = ("mafia", "don")
RED_ROLES = ("citizen", "sheriff")


def list_rated_games(
    db: Session,
    *,
    limit: int = 10,
    offset: int = 0,
    date_from: date | None = None,
    date_to: date | None = None,
    game_type: str | None = None,
    exclude_game_type: str | None = None,
    player_slug: str | None = None,
    tournament_slug: str | None = None,
) -> tuple[list[models.Game], int]:
    query = db.query(models.Game).filter(models.Game.status == "rated")
    # Фильтр приходит как календарная дата, а starts_at -- TIMESTAMPTZ. Границы
    # берём по московскому дню (клуб живёт в нём, см. app/timeutil.py), иначе
    # игра в 00:30 МСК попадёт в предыдущие сутки. Верхняя граница -- начало
    # следующего дня: "по 15-е" должно включать сам 15-й день целиком.
    if date_from:
        query = query.filter(models.Game.starts_at >= datetime.combine(date_from, time.min, tzinfo=CLUB_TZ))
    if date_to:
        day_after = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=CLUB_TZ)
        query = query.filter(models.Game.starts_at < day_after)
    if game_type:
        query = query.filter(models.Game.game_type == game_type)
    if exclude_game_type:
        # Нужно вкладке «Игры» в админке: турнирные игры там больше не
        # показываются, у них своя очередь оценки внутри этапа (см. вкладку
        # «Турниры» и app.services.tournament_service).
        query = query.filter(models.Game.game_type != exclude_game_type)
    if tournament_slug:
        query = query.filter(
            models.Game.tournament_id.in_(
                select(models.Tournament.id).where(models.Tournament.slug == tournament_slug)
            )
        )
    if player_slug:
        query = query.filter(
            models.Game.id.in_(
                db.query(models.GameParticipant.game_id)
                .join(models.Player, models.Player.id == models.GameParticipant.player_id)
                .filter(models.Player.slug == player_slug)
            )
        )

    total = query.count()
    rows = (
        # Без eager-загрузки турнира список из 100 игр давал 100 отдельных
        # запросов при сериализации GameListItem.tournament.
        query.options(selectinload(models.Game.tournament))
        .order_by(models.Game.starts_at.desc(), models.Game.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def site_counters(db: Session) -> dict[str, int]:
    """Числа для главной страницы, COUNT'ами вместо выгрузки таблиц."""
    games = (
        db.query(func.count()).select_from(models.Game).filter(models.Game.status == "rated").scalar()
    )
    players = (
        db.query(func.count())
        .select_from(models.Player)
        .filter(*visibility.public_player_criteria())
        .scalar()
    )
    tournaments = db.query(func.count()).select_from(models.Tournament).scalar()
    return {
        "games_count": games or 0,
        "players_count": players or 0,
        "tournaments_count": tournaments or 0,
    }


def get_rated_game(db: Session, game_id: int) -> models.Game | None:
    return (
        db.query(models.Game)
        # Карточка игры показывает десять участников с никами и слагами: без
        # eager-загрузки это 1 + 1 + 10 запросов на одну страницу.
        .options(
            selectinload(models.Game.participants).selectinload(models.GameParticipant.player),
            selectinload(models.Game.tournament),
            selectinload(models.Game.stage),
        )
        .filter(models.Game.id == game_id, models.Game.status == "rated")
        .one_or_none()
    )


@dataclass
class RatingRow:
    player: models.Player
    rank: int
    rating: float
    games_count: int
    win_rate: float | None
    avg_bonus: float | None


def rating_table(db: Session, *, q: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[RatingRow], int]:
    # Обучающие игры исключены ровно там же, где их исключает реплей рейтинга
    # (rating_service.UNRATED_GAME_TYPES). Без этого средний доп. балл считался
    # по большему числу игр, чем показывает соседняя колонка «Игр»: она берётся
    # из PlayerRating, куда обучающие игры не попадают вовсе.
    avg_bonus_subq = (
        db.query(
            models.GameParticipant.player_id.label("player_id"),
            func.avg(_BONUS_SQL).label("avg_bonus"),
        )
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(
            models.Game.status == "rated",
            models.Game.game_type.notin_(rating_service.UNRATED_GAME_TYPES),
        )
        .group_by(models.GameParticipant.player_id)
        .subquery()
    )

    # Ранг считает БД оконной функцией, а не enumerate() по странице выдачи.
    # Два следствия, оба нужны:
    #  * при равных рейтингах место общее (rank(), а не row_number()) -- ровно
    #    так же, как его считает compute_player_stats для страницы игрока;
    #    раньше таблица давала девяти игрокам с одинаковым рейтингом места
    #    2..10, а каждая их личная страница -- «#2»;
    #  * ранг не зависит от фильтра поиска и от смещения: найденный по нику
    #    игрок показывает своё место в клубе, а не номер строки в выдаче.
    rank_subq = (
        db.query(
            models.PlayerRating.player_id.label("player_id"),
            func.rank().over(order_by=models.PlayerRating.rating.desc()).label("rank"),
        )
        .join(models.Player, models.Player.id == models.PlayerRating.player_id)
        .filter(*visibility.public_player_criteria(), models.PlayerRating.games_count > 0)
        .subquery()
    )

    query = (
        db.query(models.Player, models.PlayerRating, avg_bonus_subq.c.avg_bonus, rank_subq.c.rank)
        .join(models.PlayerRating, models.PlayerRating.player_id == models.Player.id)
        .join(rank_subq, rank_subq.c.player_id == models.Player.id)
        .outerjoin(avg_bonus_subq, avg_bonus_subq.c.player_id == models.Player.id)
        .filter(*visibility.public_player_criteria(), models.PlayerRating.games_count > 0)
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(models.Player.nickname.ilike(like))

    total = query.count()
    # Player.id -- уникальный тай-брейкер. Без него порядок строк с одинаковым
    # рейтингом не определён, и OFFSET/LIMIT резал набор в разных порядках:
    # одни игроки попадали на две страницы сразу, другие не попадали никуда.
    rows = (
        query.order_by(rank_subq.c.rank.asc(), models.Player.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result: list[RatingRow] = []
    for player, rating, avg_bonus, rank in rows:
        games_count = rating.games_count
        win_rate = (rating.wins / games_count) if games_count else None
        result.append(
            RatingRow(
                player=player,
                rank=int(rank),
                rating=float(rating.rating),
                games_count=games_count,
                win_rate=win_rate,
                avg_bonus=float(avg_bonus) if avg_bonus is not None else None,
            )
        )
    return result, total


@dataclass
class TournamentStandingRow:
    player: models.Player
    rank: int
    games_count: int
    points_win: float
    points_judge: float
    lh_points: float
    ci: float
    removals: int
    ppk_count: int
    zk: float
    sk: float
    total_score: float


def tournament_standings(
    db: Session, *, tournament_id: int, stage_id: int | None = None
) -> list[TournamentStandingRow]:
    """Турнирная таблица: суммы игровых колонок по оценённым играм турнира,
    один игрок -- одна строка, отсортировано по total_score.

    stage_id фильтрует по конкретному этапу. stage_id=None -- НЕ "без
    фильтра", а "игры без этапа" (Game.stage_id IS NULL): для турнира без
    сеток это ровно все его игры (game_service принудительно держит там
    stage_id=NULL), так что вызывающему коду не нужно различать "турнир с
    сетками" и "турнир без сеток" -- обычный турнир просто эквивалентен
    турниру с сетками, но без единого зарегистрированного этапа.

    total_score считается суммой той же _SCORE_SQL, что и колонка «Итог» в
    карточке отдельной игры (stats_service.get_rated_game) -- сумма итогов по
    играм турнира равна итогу от суммы колонок, формула линейна по каждому
    слагаемому, так что переносить её сюда отдельной строкой не нужно.
    """
    rows = (
        db.query(
            models.GameParticipant.player_id,
            func.count().label("games_count"),
            func.sum(models.GameParticipant.points_win).label("points_win"),
            func.sum(models.GameParticipant.points_judge).label("points_judge"),
            func.sum(_LH_POINTS_SQL).label("lh_points"),
            func.sum(func.coalesce(models.GameParticipant.ci, 0)).label("ci"),
            func.sum(func.coalesce(models.GameParticipant.removals, 0)).label("removals"),
            func.count().filter(models.GameParticipant.ppk.is_(True)).label("ppk_count"),
            func.sum(func.coalesce(models.GameParticipant.zk, 0)).label("zk"),
            func.sum(func.coalesce(models.GameParticipant.sk, 0)).label("sk"),
            func.sum(_SCORE_SQL).label("total_score"),
        )
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(
            models.Game.tournament_id == tournament_id,
            models.Game.stage_id == stage_id,
            models.Game.status == "rated",
        )
        .group_by(models.GameParticipant.player_id)
        .order_by(func.sum(_SCORE_SQL).desc())
        .all()
    )
    if not rows:
        return []

    players = {
        p.id: p
        for p in db.query(models.Player).filter(models.Player.id.in_([r.player_id for r in rows])).all()
    }

    return [
        TournamentStandingRow(
            player=players[r.player_id],
            rank=idx,
            games_count=r.games_count,
            points_win=float(r.points_win),
            points_judge=float(r.points_judge),
            lh_points=float(r.lh_points),
            ci=float(r.ci),
            removals=int(r.removals),
            ppk_count=int(r.ppk_count),
            zk=float(r.zk),
            sk=float(r.sk),
            total_score=float(r.total_score),
        )
        for idx, r in enumerate(rows, start=1)
    ]


def tournament_standings_all(
    db: Session, *, tournament_id: int
) -> dict[int | None, list[TournamentStandingRow]]:
    """Сводные таблицы СРАЗУ по всем этапам турнира: {stage_id -> строки}, где
    ключ None -- игры без этапа.

    Страница турнира показывает таблицу каждого этапа плюс таблицу игр без
    этапа. Вызов tournament_standings() в цикле по этапам давал по два запроса
    на этап (агрегация + добор игроков) и рос линейно: на восьми этапах вся
    ручка стоила 36 запросов. Здесь агрегация одна на весь турнир с
    группировкой по (stage_id, player_id), игроки добираются одним IN.
    """
    rows = (
        db.query(
            models.Game.stage_id.label("stage_id"),
            models.GameParticipant.player_id,
            func.count().label("games_count"),
            func.sum(models.GameParticipant.points_win).label("points_win"),
            func.sum(models.GameParticipant.points_judge).label("points_judge"),
            func.sum(_LH_POINTS_SQL).label("lh_points"),
            func.sum(func.coalesce(models.GameParticipant.ci, 0)).label("ci"),
            func.sum(func.coalesce(models.GameParticipant.removals, 0)).label("removals"),
            func.count().filter(models.GameParticipant.ppk.is_(True)).label("ppk_count"),
            func.sum(func.coalesce(models.GameParticipant.zk, 0)).label("zk"),
            func.sum(func.coalesce(models.GameParticipant.sk, 0)).label("sk"),
            func.sum(_SCORE_SQL).label("total_score"),
        )
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(
            models.Game.tournament_id == tournament_id,
            models.Game.status == "rated",
        )
        .group_by(models.Game.stage_id, models.GameParticipant.player_id)
        .all()
    )
    if not rows:
        return {}

    players = {
        p.id: p
        for p in db.query(models.Player)
        .filter(models.Player.id.in_({r.player_id for r in rows}))
        .all()
    }

    by_stage: dict[int | None, list] = defaultdict(list)
    for r in rows:
        by_stage[r.stage_id].append(r)

    result: dict[int | None, list[TournamentStandingRow]] = {}
    for stage_id, stage_rows in by_stage.items():
        # Сортировка в Python, а не в SQL: одним запросом на весь турнир
        # ORDER BY дал бы общий порядок, а таблицы этапов нумеруются каждая
        # со своей единицы. Строк тут десятки, не тысячи.
        stage_rows.sort(key=lambda r: float(r.total_score), reverse=True)
        result[stage_id] = [
            TournamentStandingRow(
                player=players[r.player_id],
                rank=idx,
                games_count=r.games_count,
                points_win=float(r.points_win),
                points_judge=float(r.points_judge),
                lh_points=float(r.lh_points),
                ci=float(r.ci),
                removals=int(r.removals),
                ppk_count=int(r.ppk_count),
                zk=float(r.zk),
                sk=float(r.sk),
                total_score=float(r.total_score),
            )
            for idx, r in enumerate(stage_rows, start=1)
        ]
    return result


@dataclass
class PlayerStats:
    total_games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0

    black_card_games: int = 0
    black_card_wins: int = 0
    red_card_games: int = 0
    red_card_wins: int = 0
    don_games: int = 0
    don_wins: int = 0
    sheriff_games: int = 0
    sheriff_wins: int = 0

    first_kill_count: int = 0
    # Попадания ЛХ: сколько раз игрок, будучи первоубиенным, назвал
    # 0, 1, 2 или 3 чёрных. Баллы дают только 2 и 3 попадания.
    lh_hits_0: int = 0
    lh_hits_1: int = 0
    lh_hits_2: int = 0
    lh_hits_3: int = 0

    rating: float | None = None
    rating_games_count: int = 0
    rank: int | None = None

    avg_score: float | None = None
    avg_bonus: float | None = None

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.total_games if self.total_games else None

    @property
    def black_card_win_rate(self) -> float | None:
        return self.black_card_wins / self.black_card_games if self.black_card_games else None

    @property
    def red_card_win_rate(self) -> float | None:
        return self.red_card_wins / self.red_card_games if self.red_card_games else None

    @property
    def don_win_rate(self) -> float | None:
        return self.don_wins / self.don_games if self.don_games else None

    @property
    def sheriff_win_rate(self) -> float | None:
        return self.sheriff_wins / self.sheriff_games if self.sheriff_games else None


def compute_player_stats(db: Session, player_id: int) -> PlayerStats:
    won_expr = or_(
        and_(models.GameParticipant.role.in_(BLACK_ROLES), models.Game.result == "mafia_win"),
        and_(models.GameParticipant.role.in_(RED_ROLES), models.Game.result == "city_win"),
    )

    row = (
        db.query(
            func.count().label("total_games"),
            func.count().filter(won_expr).label("wins"),
            func.count()
            .filter(~won_expr, models.Game.result != "draw")
            .label("losses"),
            func.count().filter(models.Game.result == "draw").label("draws"),
            func.count().filter(models.GameParticipant.role.in_(BLACK_ROLES)).label("black_card_games"),
            func.count()
            .filter(models.GameParticipant.role.in_(BLACK_ROLES), won_expr)
            .label("black_card_wins"),
            func.count().filter(models.GameParticipant.role.in_(RED_ROLES)).label("red_card_games"),
            func.count()
            .filter(models.GameParticipant.role.in_(RED_ROLES), won_expr)
            .label("red_card_wins"),
            func.count().filter(models.GameParticipant.role == "don").label("don_games"),
            func.count().filter(models.GameParticipant.role == "don", won_expr).label("don_wins"),
            func.count().filter(models.GameParticipant.role == "sheriff").label("sheriff_games"),
            func.count()
            .filter(models.GameParticipant.role == "sheriff", won_expr)
            .label("sheriff_wins"),
            func.count().filter(models.GameParticipant.info == "first_killed").label("first_kill_count"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 0)
            .label("lh_hits_0"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 0.5)
            .label("lh_hits_1"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 1)
            .label("lh_hits_2"),
            func.count()
            .filter(models.GameParticipant.info == "first_killed", models.GameParticipant.lh == 1.5)
            .label("lh_hits_3"),
            func.avg(_SCORE_SQL).label("avg_score"),
            func.avg(_BONUS_SQL).label("avg_bonus"),
        )
        .select_from(models.GameParticipant)
        .join(models.Game, models.Game.id == models.GameParticipant.game_id)
        .filter(models.GameParticipant.player_id == player_id, models.Game.status == "rated")
        .one()
    )

    stats = PlayerStats(
        **{k: (v or 0) for k, v in row._mapping.items() if k not in ("avg_score", "avg_bonus")}
    )
    stats.avg_score = float(row.avg_score) if row.avg_score is not None else None
    stats.avg_bonus = float(row.avg_bonus) if row.avg_bonus is not None else None

    rating = db.get(models.PlayerRating, player_id)
    if rating and rating.games_count > 0:
        stats.rating = float(rating.rating)
        stats.rating_games_count = rating.games_count
        stats.rank = (
            db.query(func.count())
            .select_from(models.PlayerRating)
            .join(models.Player, models.Player.id == models.PlayerRating.player_id)
            .filter(
                *visibility.public_player_criteria(),
                models.PlayerRating.games_count > 0,
                models.PlayerRating.rating > rating.rating,
            )
            .scalar()
            + 1
        )

    return stats
