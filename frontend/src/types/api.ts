// Mirrors backend/app/schemas/*.py -- keep in sync by hand, there is no
// codegen step yet (see backend/ARCHITECTURE.md if that changes).

export type InGameRole = "mafia" | "don" | "sheriff" | "citizen";
export type GameResult = "city_win" | "mafia_win" | "draw";
export type GameType = "tournament" | "funky" | "training";
export type ParticipantInfo = "first_killed" | "killed" | "voted_out";

export interface ParticipantOut {
  seat_number: number;
  role: InGameRole;
  points_win: number;
  points_judge: number;
  lh: number | null;
  ci: number | null;
  info: ParticipantInfo | null;
  removals: number | null;
  ppk: boolean;
  zk: number | null;
  sk: number | null;
  player_slug: string;
  player_nickname: string;
}

export type RegistrationRole = "host" | "judge" | "player";

/** Кто записался на игру до неё. Приходит только из /api/admin/games/{id};
 * в публичном ответе всегда пустой массив. */
export interface GameRosterEntry {
  player_id: number;
  nickname: string;
  role: RegistrationRole;
}

export interface GameOut {
  id: number;
  starts_at: string;
  location: string | null;
  game_type: GameType;
  status: string;
  result: GameResult | null;
  notes: string | null;
  participants: ParticipantOut[];
  roster: GameRosterEntry[];
  tournament: TournamentRef | null;
  stage: TournamentStageRef | null;
}

export interface TournamentRef {
  /** Нужен админке: после оценки турнирной игры форма возвращает в карточку
   * того же турнира, а не в общий список игр. */
  id: number;
  slug: string;
  name: string;
}

export interface TournamentStageRef {
  id: number;
  name: string;
}

export interface GameListItem {
  id: number;
  starts_at: string;
  location: string | null;
  game_type: GameType;
  result: GameResult | null;
  tournament: TournamentRef | null;
}

export interface GameListOut {
  items: GameListItem[];
  total: number;
}

// --------------------------------------------------------------- расписание
// Зеркалит backend/app/schemas/schedule.py и SessionOut из schemas/bot.py.
// Раздел «Игры → Расписание» -- переехавшая из бота админка игровых дней.

/** Формат слота. Турнирные игры в расписании не заводятся -- у них своя
 * сетка этапов во вкладке «Турниры». */
export type ScheduleGameType = Exclude<GameType, "tournament">;

/** Форматы, которые заводят расписание и форма оценки бот-игр. Порядок
 * фиксированный -- им заполняются `<select>` в plan-form / session-card /
 * game-form. */
export const SCHEDULE_GAME_TYPES: ScheduleGameType[] = ["funky", "training"];

export interface SessionOut {
  id: number;
  starts_at: string;
  location: string | null;
  game_type: GameType;
  status: string;
  /** Будет ли у игры результат. false -- слот нужен только ради записи в
   * боте: подтверждать его проведение не надо, в «Ждут оценки» он не идёт. */
  needs_rating: boolean;
  registration_until: string | null;
  is_open: boolean;
  hosts: number;
  judges: number;
  players: number;
  max_players: number;
  reserves: number;
  /** Роль действующего игрока в этой игре, если он записан. Заполняет только
   * бот-ручка: ею бот помечает свои строки галочкой вместо того, чтобы
   * убирать их из списка. В расписании на сайте всегда null. */
  my_role?: string | null;
}

export interface RosterMember {
  nickname: string;
  telegram_id: number | null;
  telegram_username: string | null;
  role: RegistrationRole;
}

export interface ReserveMember {
  nickname: string;
  telegram_id: number | null;
}

export interface SessionRoster {
  registrations: RosterMember[];
  reserves: ReserveMember[];
}

export interface ScheduleSessionOut extends SessionOut {
  roster: SessionRoster;
}

export interface ScheduleDayOut {
  /** «ДД.ММ.ГГГГ» по московскому времени -- он же ключ ручки по дню. */
  day: string;
  types: GameType[];
  games_count: number;
  /** Сколько игр дня ждут ответа «состоялась или нет». */
  awaiting_count: number;
  first_starts_at: string;
}

export interface SchedulePlanPreviewOut {
  starts_at_list: string[];
  conflicts: string[];
}

/** Чем можно отсортировать таблицу рейтинга (параметр sort у /api/rating).
 * Зеркалит stats_service.RATING_SORTS. */
export type RatingSort = "rating" | "win_rate" | "avg_bonus";

export interface RatingRowOut {
  /** null у найденного поиском игрока без единой сыгранной игры: места в
   * рейтинге у него ещё нет. В таблице рисуется прочерком. */
  rank: number | null;
  slug: string;
  nickname: string;
  photo_url: string | null;
  rating: number;
  games_count: number;
  win_rate: number | null;
  avg_bonus: number | null;
}

export interface RatingTableOut {
  items: RatingRowOut[];
  total: number;
}

export interface RatingLegendItem {
  symbol: string;
  text: string;
}

export interface RatingKTier {
  condition: string;
  k: number;
  removal_penalty: number;
  ppk_penalty: number;
}

export interface GameTypeWeight {
  game_type: GameType;
  label: string;
  weight: number;
  rated: boolean;
}

/** Зеркалит backend RatingFormulaOut: числа в k_tiers/game_type_weights
 * получены вызовом настоящих формул рейтинга, а не переписаны в текст руками
 * -- см. rating_service.describe_formula. */
export interface RatingFormulaOut {
  intro: string;
  start_rating: number;
  formula: string;
  legend: RatingLegendItem[];
  expected_score_min: number;
  expected_score_max: number;
  k_tiers: RatingKTier[];
  note: string;
  game_type_weights: GameTypeWeight[];
  training_note: string;
}

export interface PlayerListItem {
  slug: string;
  nickname: string;
  photo_url: string | null;
}

export interface PlayerPublic {
  slug: string;
  nickname: string;
  full_name: string | null;
  age: number | null;
  favorite_role: InGameRole | null;
  experience: string | null;
  bio: string | null;
  photo_url: string | null;
}

export interface PlayerStatsOut {
  total_games: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number | null;

  black_card_games: number;
  black_card_win_rate: number | null;
  red_card_games: number;
  red_card_win_rate: number | null;
  don_games: number;
  don_win_rate: number | null;
  sheriff_games: number;
  sheriff_win_rate: number | null;

  first_kill_count: number;
  lh_distribution: Record<LhHits, number>;

  rating: number | null;
  rating_games_count: number;
  rank: number | null;

  avg_score: number | null;
  avg_bonus: number | null;
}

export interface PlayerDetailOut {
  player: PlayerPublic;
  stats: PlayerStatsOut;
}

export interface PlayerAdminOut {
  id: number;
  slug: string;
  nickname: string;
  full_name: string | null;
  age: number | null;
  favorite_role: InGameRole | null;
  experience: string | null;
  bio: string | null;
  photo_url: string | null;
  is_active: boolean;
  confirmation_status: ConfirmationStatus;
  rejection_reason: string | null;
  is_bot_admin: boolean;
  is_site_admin: boolean;
  site_username: string | null;
  telegram_id: number | null;
  telegram_username: string | null;
  created_at: string;
}

/** Модерация игрока, зарегистрировавшегося через бота (см. бэкенд,
 * models.ConfirmationStatus). Пока статус не confirmed, игрока нет ни в
 * рейтинге, ни в списке игроков, ни на своей странице. */
export type ConfirmationStatus = "pending" | "confirmed" | "rejected";

/** Роль в конкретной игре недели: три роли записи плюс резерв. */
export type PassListRole = RegistrationRole | "reserve";

export const PASS_LIST_ROLE_LABELS: Record<PassListRole, string> = {
  player: "Игрок",
  host: "Ведущий",
  judge: "Судья",
  reserve: "Резерв",
};

export interface PassListGameOut {
  game_id: number;
  starts_at: string;
  game_type: GameType;
  location: string | null;
  role: PassListRole;
}

export interface PassListEntryOut {
  player_id: number;
  nickname: string;
  full_name: string | null;
  phone: string | null;
  confirmation_status: ConfirmationStatus;
  games: PassListGameOut[];
}

export interface PassListOut {
  week_start: string;
  week_end: string;
  rollover_weekday: number;
  rollover_time: string;
  entries: PassListEntryOut[];
}

export interface PassWeekSettings {
  pass_week_rollover_weekday: number;
  pass_week_rollover_time: string;
}

/** 0 = понедельник, как в Python datetime.weekday() на бэкенде. */
export const WEEKDAY_LABELS = [
  "Понедельник",
  "Вторник",
  "Среда",
  "Четверг",
  "Пятница",
  "Суббота",
  "Воскресенье",
] as const;

export interface LoginOut {
  nickname: string;
  is_site_admin: boolean;
}

export interface ParticipantInput {
  player_id: number;
  seat_number: number;
  role: InGameRole;
  points_win?: number;
  points_judge?: number;
  lh?: number | null;
  ci?: number | null;
  info?: ParticipantInfo | null;
  removals?: number | null;
  ppk?: boolean;
  zk?: number | null;
  sk?: number | null;
}

export interface SiteStats {
  games_count: number;
  players_count: number;
  tournaments_count: number;
}

export interface TournamentListItem {
  slug: string;
  name: string;
  location: string | null;
  games_count: number;
}

export interface TournamentPublic {
  slug: string;
  name: string;
  description: string | null;
  location: string | null;
  starts_at: string;
  ends_at: string;
}

export interface TournamentStandingOut {
  rank: number;
  slug: string;
  nickname: string;
  photo_url: string | null;
  games_count: number;
  points_win: number;
  points_judge: number;
  lh_points: number;
  ci: number;
  removals: number;
  ppk_count: number;
  zk: number;
  sk: number;
  total_score: number;
  /** Осмысленно только внутри таблицы конкретного этапа -- прошёл ли игрок
   * дальше по итогам этой сводной таблицы (отмечается админом вручную). */
  advanced: boolean;
}

/** Один пронумерованный слот этапа для публичной страницы турнира. */
export interface TournamentStagePublicGameOut {
  number: number;
  id: number;
  starts_at: string;
  status: string;
  result: GameResult | null;
}

/** Этап турнира (сетка по олимпийской системе для >10 участников) со своей
 * сводной таблицей. Обычный турнир (<=10 игроков) этапов не имеет вообще --
 * TournamentDetailOut.stages для него пуст. */
export interface TournamentStageDetailOut {
  id: number;
  name: string;
  order: number;
  /** Таблица финального этапа развёрнута на странице турнира по умолчанию,
   * остальные -- свёрнуты. Только один этап турнира может быть финальным. */
  is_final: boolean;
  standings: TournamentStandingOut[];
  games: TournamentStagePublicGameOut[];
}

/** Кандидат номинации со статистикой по финальному столу. Зеркалит
 * backend/app/schemas/tournament.py::AwardCandidateOut. */
export interface AwardCandidateOut {
  slug: string;
  nickname: string;
  photo_url: string | null;
  /** Место в таблице финального стола -- им же разрешается равенство баллов. */
  rank: number;
  games_count: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  points_judge: number;
  lh_points: number;
  /** Средний доп. балл за игру (судейские + ЛХ) в зачёте номинации. */
  avg_bonus: number | null;
  /** Зачётная величина номинации: балл за игру (ролевые + MVP) или сумма
   * баллов таблицы (места турнира). */
  score: number;
  total_score: number;
}

export interface TournamentAwardOut {
  nomination: string;
  title: string;
  formula: string;
  winner: AwardCandidateOut | null;
  /** Победителя выбрал админ вручную, а не расчёт. */
  manual: boolean;
  /** Приходит только в админской ручке -- на публичной странице пуст. */
  candidates: AwardCandidateOut[];
}

/** Ответ админской ручки предпросмотра номинаций. */
export interface TournamentAwardsOut {
  published: boolean;
  table_name: string | null;
  problem: string | null;
  items: TournamentAwardOut[];
}

/** Номинации-места турнира -- показываются отдельным блоком «Призёры». */
export const PLACE_NOMINATIONS = ["first_place", "second_place", "third_place"];

export interface TournamentDetailOut {
  tournament: TournamentPublic;
  games_count: number;
  // Общая таблица по всему турниру. У турнира без этапов -- все его игры
  // (ровно как раньше). У турнира С этапами -- только игры, ещё не
  // разнесённые по этапам (обычно пусто).
  standings: TournamentStandingOut[];
  stages: TournamentStageDetailOut[];
  /** Пусто, пока админ не опубликовал блок номинаций. */
  awards: TournamentAwardOut[];
  /** Стол, по которому посчитаны номинации (null -- турнир без сеток). */
  awards_table_name: string | null;
}

export interface TournamentAdminOut {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  location: string | null;
  starts_at: string;
  ends_at: string;
  created_at: string;
  games_count: number;
}

export interface TournamentStageOut {
  id: number;
  tournament_id: number;
  name: string;
  order: number;
  is_final: boolean;
  /** Число ОЦЕНЁННЫХ игр этапа -- не общее число слотов (см. TournamentStageGameOut). */
  games_count: number;
}

/** Один игровой слот турнира/этапа -- и уже оценённый, и ещё пустой (status
 * ещё 'scheduled', result=null). Оценивается через общий PUT /admin/games/{id}. */
export interface TournamentStageGameOut {
  id: number;
  starts_at: string;
  location: string | null;
  status: string;
  result: GameResult | null;
}

export interface TournamentStageInput {
  name: string;
  order?: number | null;
  /** Сколько пустых игровых слотов создать сразу вместе с этапом. */
  games_count: number;
  is_final?: boolean;
}

export interface TournamentInput {
  name: string;
  slug: string;
  starts_at: string;
  ends_at: string;
  description?: string | null;
  location?: string | null;
}

export interface GameCreateInput {
  starts_at: string;
  location?: string | null;
  /** Турнирные игры тут больше не создаются -- см. вкладку «Турниры». */
  game_type: Exclude<GameType, "tournament">;
  result: GameResult;
  notes?: string | null;
  participants: ParticipantInput[];
}

export interface GameUpdateInput {
  starts_at?: string;
  location?: string | null;
  /** Только для не-турнирных игр -- сменить формат турнирной игры отсюда
   * нельзя, привязка к турниру/этапу фиксируется один раз при создании слота. */
  game_type?: Exclude<GameType, "tournament">;
  result?: GameResult;
  notes?: string | null;
  participants?: ParticipantInput[];
}

export interface PlayerCreateInput {
  nickname: string;
  slug: string;
  full_name?: string | null;
  age?: number | null;
  favorite_role?: InGameRole | null;
  experience?: string | null;
  bio?: string | null;
}

export type PlayerUpdateInput = Partial<PlayerCreateInput>;

export interface SiteAccessGrantOut {
  site_username: string;
  temp_password: string;
}

export interface ApiErrorDetail {
  type?: string;
  loc?: (string | number)[];
  msg?: string;
}

export const ROLE_LABELS: Record<InGameRole, string> = {
  mafia: "Мафия",
  don: "Дон",
  sheriff: "Шериф",
  citizen: "Мирный",
};

export const RESULT_LABELS: Record<GameResult, string> = {
  city_win: "Победа мирных",
  mafia_win: "Победа мафии",
  draw: "Ничья",
};

export const GAME_TYPE_LABELS: Record<GameType, string> = {
  tournament: "Турнир",
  funky: "Фанки",
  training: "Обучающая",
};

/** game_participants.lh хранит ПОПАДАНИЯ ЛХ, а не баллы: клубная запись
 * 0 / 0.5 / 1 / 1.5 означает 0/3, 1/3, 2/3, 3/3 названных чёрных. Баллы из них
 * выводятся отдельно: 0/3 и 1/3 не дают ничего, 2/3 -> 0.5, 3/3 -> 1.
 * Зеркалит backend rating_service.LH_POINTS. */
export type LhHits = "0/3" | "1/3" | "2/3" | "3/3";

export const LH_SCALE: { raw: number; hits: LhHits; points: number }[] = [
  { raw: 0, hits: "0/3", points: 0 },
  { raw: 0.5, hits: "1/3", points: 0 },
  { raw: 1, hits: "2/3", points: 0.5 },
  { raw: 1.5, hits: "3/3", points: 1 },
];

/** Сырое значение поля -> «2/3», как это читает судья. */
export function lhHits(raw: number | null | undefined): LhHits | null {
  return LH_SCALE.find((s) => s.raw === raw)?.hits ?? null;
}

/** Сырое значение поля -> баллы (0, 0, 0.5, 1). */
export function lhPoints(raw: number | null | undefined): number {
  return LH_SCALE.find((s) => s.raw === raw)?.points ?? 0;
}

// Штрафы в игровых баллах -- зеркалит backend stats_service.py
// (SCORE_PENALTY_PER_REMOVAL / SCORE_PENALTY_PPK). ЖК и СК уже хранятся как
// баллы, удаления и ППК -- как счётчик и флаг, поэтому им нужны ставки. Это не
// то же самое, что штрафы в очках Эло (там 3..15 очков рейтинга).
// Ставка за ППК -- 2.5 балла, по регламенту клуба. Ставка за удаление
// регламентом не подтверждена -- см. комментарий в бэкенде.
export const SCORE_PENALTY_PER_REMOVAL = 0.5;
export const SCORE_PENALTY_PPK = 2.5;

/** Итог по игроку за игру: все баллы минус все штрафы. Та же формула, что и
 * backend stats_service._SCORE_SQL (avg_score до усреднения по играм). */
export function participantScore(p: {
  points_win: number;
  points_judge: number;
  lh: number | null;
  ci: number | null;
  zk: number | null;
  sk: number | null;
  removals: number | null;
  ppk: boolean;
}): number {
  const points = p.points_win + p.points_judge + lhPoints(p.lh) + (p.ci ?? 0);
  const penalty =
    (p.zk ?? 0) +
    (p.sk ?? 0) +
    (p.removals ?? 0) * SCORE_PENALTY_PER_REMOVAL +
    (p.ppk ? SCORE_PENALTY_PPK : 0);
  return points - penalty;
}

export const INFO_LABELS: Record<ParticipantInfo, string> = {
  first_killed: "ПУ",
  killed: "Убит",
  voted_out: "Заголосован",
};
