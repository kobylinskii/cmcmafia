import type { Metadata } from "next";
import { Unbounded, Golos_Text, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const unbounded = Unbounded({
  variable: "--font-unbounded",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});

const golos = Golos_Text({
  variable: "--font-golos",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
const DESCRIPTION =
  "Клуб спортивной мафии ВМК МГУ: результаты игр, рейтинг и статистика игроков.";

export const metadata: Metadata = {
  // metadataBase нужен, чтобы относительные пути в openGraph.images
  // разворачивались в абсолютные URL -- без него превью не собирается.
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Мафия ВМК",
    template: "%s — Мафия ВМК",
  },
  description: DESCRIPTION,
  // Ссылками на сайт делятся в телеграме (у клуба там бот) -- без этих тегов
  // каждая приходила серой строкой без картинки и заголовка.
  openGraph: {
    type: "website",
    locale: "ru_RU",
    siteName: "Мафия ВМК",
    title: "Мафия ВМК",
    description: DESCRIPTION,
    url: SITE_URL,
    images: [{ url: "/logo/logo-badge.png", width: 1200, height: 1200, alt: "Мафия ВМК" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Мафия ВМК",
    description: DESCRIPTION,
    images: ["/logo/logo-badge.png"],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ru"
      className={`${unbounded.variable} ${golos.variable} ${jetbrainsMono.variable} h-full`}
    >
      {/* Без JS IntersectionObserver не отработает и блоки с .reveal остались
          бы невидимыми навсегда -- показываем их сразу. */}
      <noscript>
        <style>{`.reveal { opacity: 1; transform: none; }`}</style>
      </noscript>
      <body className="min-h-full antialiased">
        <div className="grain-overlay" aria-hidden="true" />
        {children}
      </body>
    </html>
  );
}
