from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GameStatus(str, enum.Enum):
    scheduled = "scheduled"
    registration_closed = "registration_closed"
    played = "played"
    rated = "rated"


class GameResult(str, enum.Enum):
    city_win = "city_win"
    mafia_win = "mafia_win"
    draw = "draw"


class RegistrationRole(str, enum.Enum):
    host = "host"
    judge = "judge"
    player = "player"


class InGameRole(str, enum.Enum):
    mafia = "mafia"
    don = "don"
    sheriff = "sheriff"
    citizen = "citizen"


class ParticipantInfo(str, enum.Enum):
    first_killed = "first_killed"
    killed = "killed"
    voted_out = "voted_out"


class GameType(str, enum.Enum):
    tournament = "tournament"
    funky = "funky"
    training = "training"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150))
    age: Mapped[int | None] = mapped_column(SmallInteger)
    favorite_role: Mapped[str | None] = mapped_column(String(10))
    experience: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(Text)

    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    telegram_username: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    salutation: Mapped[str | None] = mapped_column(String(20))
    affiliation: Mapped[str | None] = mapped_column(String(20))
    can_play: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    site_username: Mapped[str | None] = mapped_column(String(50), unique=True)
    site_password_hash: Mapped[str | None] = mapped_column(Text)
    is_site_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_bot_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    rating: Mapped[PlayerRating | None] = relationship(back_populates="player", uselist=False)

    __table_args__ = (
        CheckConstraint(
            "site_username IS NULL OR site_password_hash IS NOT NULL",
            name="ck_players_site_creds",
        ),
        CheckConstraint(
            r"slug ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'",
            name="ck_players_slug_format",
        ),
        Index("idx_players_active", "is_active"),
        Index("idx_players_is_bot_admin", "is_bot_admin", postgresql_where=text("is_bot_admin")),
    )


class PendingBotAdmin(Base):
    __tablename__ = "pending_bot_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tournament(Base):
    """Турнир как самостоятельная сущность: у него своё название, описание,
    место проведения и период проведения, и на него ссылаются игры с
    game_type='tournament'.

    Турнирные игры больше не создаются через бота (ни регистрации, ни
    создания сессий для game_type='tournament' -- см. GAME_TYPES в
    app/schemas/bot.py) -- вся турнирная сетка целиком заводится и
    редактируется на сайте, поэтому связь games.tournament_id обязательна для
    оценённых турнирных игр (см. ck_games_rated_tournament_has_tournament) без
    компромисса на "бот ещё не знает турнир", актуального для старой модели.
    """

    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    # Период проведения турнира. Обязателен у любого турнира (даже простого,
    # без этапов) -- помимо чисто информационного показа, дата начала служит
    # плейсхолдером для только что созданных игровых слотов этапа: реальная
    # дата каждой конкретной игры выставляется админом вручную позже, т.к.
    # турнир обычно идёт несколько дней подряд или с недельным интервалом.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    games: Mapped[list[Game]] = relationship(back_populates="tournament")
    stages: Mapped[list[TournamentStage]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", order_by="TournamentStage.order"
    )

    __table_args__ = (
        CheckConstraint(
            r"slug ~ '^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$'",
            name="ck_tournaments_slug_format",
        ),
        CheckConstraint("ends_at >= starts_at", name="ck_tournaments_ends_after_starts"),
    )


class TournamentStage(Base):
    """Отборочный этап турнира (по олимпийской системе, когда участников > 10):
    "Отборочный стол 1", "Финал" и т.п. -- свободное название, задаёт админ.

    Существует ТОЛЬКО когда турниру нужна сетка. Обычный турнир (участников
    помещается за один стол, играется просто серия из N игр) этапов не имеет
    вообще -- games.stage_id остаётся NULL, и вся публичная/турнирная логика
    работает как раньше (см. ARCHITECTURE.md и game_service._resolve_stage).
    """

    __tablename__ = "tournament_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # Порядок отображения на странице турнира -- не обязательно совпадает с
    # порядком создания (админ мог создать этапы не по порядку). Не пытаемся
    # угадывать "это финал" по номеру: название -- свободный текст.
    order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    # Ровно один этап турнира может быть отмечен финальным -- на публичной
    # странице турнира его таблица развёрнута по умолчанию, остальные этапы
    # свёрнуты (см. tournament_service.create_stage/update_stage, где
    # проставление true у одного этапа снимает флаг с остальных).
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tournament: Mapped[Tournament] = relationship(back_populates="stages")
    games: Mapped[list[Game]] = relationship(back_populates="stage")
    advances: Mapped[list[TournamentStageAdvance]] = relationship(
        back_populates="stage", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tournament_id", "name", name="uq_tournament_stages_tournament_name"),
        Index("idx_tournament_stages_tournament", "tournament_id"),
    )


class TournamentStageAdvance(Base):
    """Кто прошёл из этапа дальше. Простая пара (этап, игрок) без отдельного
    булева поля: наличие строки и значит "прошёл". Ставится админом вручную
    одним разом по всей сводной таблице этапа, когда все игры этапа сыграны --
    никакого автоматического правила прохода нет (см. ARCHITECTURE.md)."""

    __tablename__ = "tournament_stage_advances"

    stage_id: Mapped[int] = mapped_column(
        ForeignKey("tournament_stages.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stage: Mapped[TournamentStage] = relationship(back_populates="advances")
    player: Mapped[Player] = relationship()


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    game_type: Mapped[str] = mapped_column(String(20), nullable=False, default=GameType.tournament.value)
    registration_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_players: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default=GameStatus.scheduled.value)
    result: Mapped[str | None] = mapped_column(String(10))
    results_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)
    # RESTRICT, а не SET NULL: обнуление увело бы оценённые турнирные игры в
    # нарушение чек-констрейнта ниже, а каскад стёр бы историю. Турнир с
    # играми удалить нельзя -- сначала переносят игры.
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournaments.id", ondelete="RESTRICT")
    )
    # RESTRICT по той же причине, что и у tournament_id: удалить этап с уже
    # внесёнными играми нельзя, сначала их переносят на другой этап или в
    # турнир без этапов. NULL -- игра не принадлежит никакому этапу (обычный
    # турнир без сетки, либо не-турнирная игра).
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament_stages.id", ondelete="RESTRICT")
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    participants: Mapped[list[GameParticipant]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    registrations: Mapped[list[Registration]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    reserves: Mapped[list[Reserve]] = relationship(back_populates="game", cascade="all, delete-orphan")
    tournament: Mapped[Tournament | None] = relationship(back_populates="games")
    stage: Mapped[TournamentStage | None] = relationship(back_populates="games")

    __table_args__ = (
        CheckConstraint(
            "status <> 'rated' OR result IS NOT NULL",
            name="ck_games_rated_has_result",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('city_win','mafia_win','draw')",
            name="ck_games_result_enum",
        ),
        CheckConstraint(
            "status IN ('scheduled','registration_closed','played','rated')",
            name="ck_games_status_enum",
        ),
        CheckConstraint(
            "game_type IN ('tournament','funky','training')",
            name="ck_games_type_enum",
        ),
        CheckConstraint(
            "status <> 'rated' OR game_type <> 'tournament' OR tournament_id IS NOT NULL",
            name="ck_games_rated_tournament_has_tournament",
        ),
        Index("idx_games_starts_at", "starts_at", "id"),
        Index("idx_games_tournament", "tournament_id"),
        Index("idx_games_stage", "stage_id"),
        Index("idx_games_status", "status"),
    )


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    available_from: Mapped[str | None] = mapped_column(Text)
    available_until: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    game: Mapped[Game] = relationship(back_populates="registrations")
    player: Mapped[Player] = relationship()

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_registrations_game_player"),
        CheckConstraint("role IN ('host','judge','player')", name="ck_registrations_role_enum"),
        Index("idx_registrations_player", "player_id"),
        Index("idx_registrations_game", "game_id"),
    )


class Reserve(Base):
    __tablename__ = "reserves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    game: Mapped[Game] = relationship(back_populates="reserves")
    player: Mapped[Player] = relationship()

    __table_args__ = (UniqueConstraint("game_id", "player_id", name="uq_reserves_game_player"),)


class GameParticipant(Base):
    __tablename__ = "game_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="RESTRICT"), nullable=False)
    seat_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)

    points_win: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0)
    points_judge: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0)
    lh: Mapped[float | None] = mapped_column(Numeric(3, 2))
    ci: Mapped[float | None] = mapped_column(Numeric(5, 2))
    info: Mapped[str | None] = mapped_column(String(20))
    removals: Mapped[int | None] = mapped_column(SmallInteger)
    ppk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    zk: Mapped[float | None] = mapped_column(Numeric(3, 1))
    sk: Mapped[float | None] = mapped_column(Numeric(3, 1))

    game: Mapped[Game] = relationship(back_populates="participants")
    player: Mapped[Player] = relationship()

    __table_args__ = (
        UniqueConstraint("game_id", "seat_number", name="uq_participants_game_seat"),
        UniqueConstraint("game_id", "player_id", name="uq_participants_game_player"),
        CheckConstraint("seat_number BETWEEN 1 AND 10", name="ck_participants_seat_range"),
        CheckConstraint("role IN ('mafia','don','sheriff','citizen')", name="ck_participants_role_enum"),
        CheckConstraint(
            "info IS NULL OR info IN ('first_killed','killed','voted_out')",
            name="ck_participants_info_enum",
        ),
        # Шкала попаданий ЛХ, а не диапазон: 0/3, 1/3, 2/3, 3/3. Промежуточные
        # значения таблица баллов (rating_service.LH_POINTS) не знает и молча
        # отдаёт по ним ноль -- см. миграцию a1c4f7e29b03.
        CheckConstraint("lh IS NULL OR lh IN (0, 0.5, 1, 1.5)", name="ck_participants_lh_scale"),
        CheckConstraint("removals IS NULL OR removals >= 0", name="ck_participants_removals_nonneg"),
        CheckConstraint("zk IS NULL OR zk >= 0", name="ck_participants_zk_nonneg"),
        CheckConstraint("sk IS NULL OR sk >= 0", name="ck_participants_sk_nonneg"),
        Index("idx_participants_player", "player_id"),
        Index("idx_participants_game", "game_id"),
    )


class PlayerRating(Base):
    __tablename__ = "player_rating"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    rating: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False, default=1000)
    games_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    draws: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    player: Mapped[Player] = relationship(back_populates="rating")

    __table_args__ = (Index("idx_rating_current", "rating"),)


class PlayerRatingHistory(Base):
    __tablename__ = "player_rating_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    rating_before: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    rating_after: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    delta: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    k_coefficient: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    expected_score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    sa: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    penalty: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)

    __table_args__ = (UniqueConstraint("player_id", "game_id", name="uq_rating_history_player_game"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    entity: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    diff: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint("actor_kind IN ('site','bot')", name="ck_audit_actor_kind_enum"),)
