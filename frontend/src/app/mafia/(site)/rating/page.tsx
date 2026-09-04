import type { Metadata } from "next";
import { serverGet } from "@/lib/api";
import type { RatingTableOut } from "@/types/api";
import { Container } from "@/components/ui/container";
import { RatingTable } from "@/components/rating/rating-table";
import { RatingSearchInput } from "@/components/rating/search-input";
import { firstParam } from "@/lib/search-params";

export const metadata: Metadata = { title: "Рейтинг" };
export const dynamic = "force-dynamic";

export default async function RatingPage({ searchParams }: PageProps<"/mafia/rating">) {
  const params = await searchParams;
  const q = firstParam(params, "q");

  const [rating, formula] = await Promise.all([
    serverGet<RatingTableOut>("/api/rating", { q, limit: 100 }),
    serverGet<{ text: string }>("/api/rating/formula"),
  ]);

  return (
    <Container className="py-14">
      <div className="max-w-2xl">
        <h1 className="font-display text-3xl font-medium text-ink-50 md:text-4xl">Рейтинг клуба</h1>
        <p className="mt-4 whitespace-pre-line text-sm leading-relaxed text-ink-300">{formula.text}</p>
      </div>

      <div className="mt-10 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-ink-400">{rating.total} игроков в рейтинге</p>
        <RatingSearchInput />
      </div>

      <div className="mt-4">
        <RatingTable rows={rating.items} />
      </div>
    </Container>
  );
}
