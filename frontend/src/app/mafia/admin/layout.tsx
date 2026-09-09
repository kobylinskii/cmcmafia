// nonce из CSP (см. src/proxy.ts) проставляется только при ДИНАМИЧЕСКОМ
// рендере. Страницы админки клиентские и по умолчанию пререндерятся статикой
// на сборке -- тогда их бутстрап-скрипты Next остаются без nonce и строгий
// script-src их блокирует (белый экран). Форсим динамику на всю ветку
// /mafia/admin/** здесь, одним layout: в client-странице логина
// `export const dynamic` не действует.
export const dynamic = "force-dynamic";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return children;
}
