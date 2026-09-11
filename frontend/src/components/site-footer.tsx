import Link from "next/link";
import { TelegramLogo } from "@phosphor-icons/react/dist/ssr";
import { Container } from "@/components/ui/container";
import { LogoMark } from "@/components/logo";

// VK -- заглушка, пока у клуба нет группы; Telegram уже настоящий.
// Phosphor has no VK glyph, so that one renders as a text mark instead.
const SOCIAL_LINKS = [
  { href: "https://t.me/cmc_mafia", label: "Telegram", icon: TelegramLogo },
  { href: "https://vk.com/", label: "VK", icon: null },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-ink-800 mt-24">
      <Container className="flex flex-col gap-8 py-12 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <LogoMark size={64} />
          <div>
            <p className="font-display text-base text-ink-50">Мафия ВМК</p>
            <p className="text-sm text-ink-400">Клуб спортивной мафии ВМК МГУ</p>
            {/* Ссылка в подвале, а не где-то в меню: 152-ФЗ требует
                свободного доступа к политике, то есть с любой страницы. */}
            <Link
              href="/privacy"
              className="mt-1 inline-block text-sm text-ink-500 underline underline-offset-4 hover:text-ink-300"
            >
              Обработка персональных данных
            </Link>
          </div>
        </div>
        <nav className="flex items-center gap-4 text-ink-300">
          {SOCIAL_LINKS.map(({ href, label, icon: Icon }) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={label}
              title={label}
              className="inline-flex h-11 w-11 items-center justify-center rounded-pill border border-ink-700 hover:border-brand-500/60 hover:text-brand-300"
            >
              {Icon ? <Icon size={16} weight="fill" /> : <span className="text-[11px] font-semibold">VK</span>}
            </a>
          ))}
        </nav>
      </Container>
    </footer>
  );
}
