import { NextRequest } from "next/server";
import { INTERNAL_API_URL } from "@/lib/api";

/**
 * Отдаёт фото игрока с бэкенда через сервер Next.
 *
 * На проде NEXT_PUBLIC_API_URL пустой, значит mediaUrl() возвращает
 * ОТНОСИТЕЛЬНЫЙ путь `/media/players/x.jpg` -- и next/image считает такую
 * картинку локальной: оптимизатор идёт за файлом на сам сервер Next
 * (http://localhost:3000/media/players/x.jpg). Файлов там нет, они лежат в
 * волюме, который наружу раздаёт nginx (см. nginx/nginx.conf) -- оптимизатор
 * получал 404, <Image> рисовался битым, и в левом верхнем углу вместо
 * аватара был виден alt, то есть ник игрока.
 *
 * Снаружи этот роут почти не используется: nginx перехватывает
 * /media/players/ раньше, чем запрос дойдёт до фронтенда. Он существует
 * ровно ради внутреннего запроса оптимизатора -- и ради `next dev` без
 * nginx.
 *
 * Почему не rewrites() в next.config: они вычисляются на сборке и
 * запекаются в routes-manifest.json, а API_INTERNAL_URL появляется только в
 * рантайме контейнера -- на этапе `docker compose build` его нет.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  // Имена файлов генерирует бэкенд (uuid4().hex + ".jpg"), но роут публичный:
  // без этой проверки путь из запроса ушёл бы в URL бэкенда как есть.
  if (path.some((segment) => segment.includes("/") || segment.includes(".."))) {
    return new Response("Not found", { status: 404 });
  }

  const upstream = await fetch(
    `${INTERNAL_API_URL}/media/players/${path.map(encodeURIComponent).join("/")}`,
    // Без Data Cache: у него лимит в пару мегабайт на запись, а тут бинарь
    // произвольного размера. Кеширование берут на себя оптимизатор картинок
    // (он складывает свой результат сам) и Cache-Control ниже.
    { cache: "no-store" },
  ).catch(() => null);

  if (!upstream || !upstream.ok) {
    return new Response("Not found", { status: 404 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "image/jpeg",
      "Cache-Control": "public, max-age=86400",
    },
  });
}
