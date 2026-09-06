import { revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";
import { PUBLIC_CACHE_TAG } from "@/lib/api-server";

/**
 * Сброс кеша публичных страниц. Дёргается автоматически из lib/api.ts после
 * любой удачной изменяющей операции в админке -- см. clientFetch.
 *
 * Публичные страницы кешируют ответы бэкенда на пять минут (иначе каждый заход
 * любого посетителя означает полный SSR и поход в API). Без этого сброса
 * правка в админке не появлялась на сайте до истечения окна: админ
 * переименовывал турнир, в панели всё верно, а на публичной вкладке ещё
 * старое название.
 *
 * Гейт -- наличие сессионной куки, той же, что проверяет proxy.ts. Это не
 * авторизация (её делает бэкенд на самой мутации), а защита от того, чтобы
 * посторонний сбрасывал кеш в цикле: сама по себе операция безопасна, но
 * бесплатно ронять кеш чужого сайта не должно быть можно.
 */
export async function POST(request: NextRequest) {
  if (!request.cookies.has("refresh_token")) {
    return NextResponse.json({ revalidated: false }, { status: 401 });
  }
  // Второй аргумент в Next 16 обязателен: профиль cacheLife или { expire }.
  // expire: 0 -- пометить помеченное тегом просроченным прямо сейчас, чтобы
  // следующий заход на публичную страницу сходил в API за свежими данными.
  revalidateTag(PUBLIC_CACHE_TAG, { expire: 0 });
  return NextResponse.json({ revalidated: true });
}
