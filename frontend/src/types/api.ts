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

export interface GameOut {
  id: number;
  starts_at: string;
  location: string | null;
  game_type: GameType;
  status: string;
  result: GameResult | null;
  notes: string | null;
  participants: ParticipantOut[];
}

export interface GameListItem {
  id: number;
  starts_at: string;
  location: string | null;
  game_type: GameType;
  result: GameResult | null;
}

export interface GameListOut {
  items: GameListItem[];
  total: number;
}

export interface RatingRowOut {
  rank: number;
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
  lh_distribution: Record<"0" | "0.5" | "1" | "1.5", number>;

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
  is_bot_admin: boolean;
  is_site_admin: boolean;
  site_username: string | null;
  telegram_id: number | null;
  telegram_username: string | null;
  created_at: string;
}

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

export interface GameCreateInput {
  starts_at: string;
  location?: string | null;
  game_type: GameType;
  result: GameResult;
  notes?: string | null;
  participants: ParticipantInput[];
}

export type GameUpdateInput = Partial<GameCreateInput>;

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

export const INFO_LABELS: Record<ParticipantInfo, string> = {
  first_killed: "ПУ",
  killed: "Убит",
  voted_out: "Заголосован",
};
