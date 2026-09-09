// Контраст текста по WCAG AA (4.5:1) для обеих тем.
//
// Палитра живёт в токенах, а светлая тема -- это их переопределение в
// globals.css, так что одна неудачная правка цвета тихо роняет читаемость
// сразу на десятках страниц. Скрипт читает оба набора прямо из CSS и проверяет
// пары, которые реально встречаются в разметке: вторичный текст на
// поверхностях, акцентный красный на подложках алертов и белый на заливке
// кнопок.
//
//   node scripts/check-contrast.mjs
//
// Падает с кодом 1 и списком проваленных пар.

import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");

function vars(block) {
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,8});/g)].map((m) => [m[1], m[2]]));
}

const themeBlock = css.match(/@theme\s*\{([\s\S]*?)\n\}/);
const lightBlock = css.match(/html\[data-theme="light"\]\s*\{([\s\S]*?)\n\}/);
if (!themeBlock || !lightBlock) throw new Error("не нашёл @theme или блок светлой темы в globals.css");

const dark = { ...vars(themeBlock[1]), "page-bg": css.match(/--page-bg:\s*(#[0-9a-fA-F]{3,8});/)[1] };
const light = { ...dark, ...vars(lightBlock[1]) };

const lum = (hex) => {
  const [r, g, b] = hex.replace("#", "").match(/../g).map((h) => parseInt(h, 16) / 255);
  const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
// Цвет с прозрачностью поверх подложки -- так собираются подложки алертов
// (bg-brand-900/30) и активные строки таблиц.
const over = (fg, bg, alpha) => {
  const px = (h) => h.replace("#", "").match(/../g).map((x) => parseInt(x, 16));
  const [a, b] = [px(fg), px(bg)];
  return "#" + a.map((v, i) => Math.round(v * alpha + b[i] * (1 - alpha)).toString(16).padStart(2, "0")).join("");
};

const AA = 4.5;
const failures = [];

function check(theme, name, fg, bg, min = AA) {
  const r = ratio(fg, bg);
  const line = `${theme.padEnd(7)} ${name.padEnd(34)} ${r.toFixed(2)}:1`;
  if (r < min) failures.push(`${line}  < ${min}`);
  else console.log(line);
}

for (const [name, t] of [
  ["тёмная", dark],
  ["светлая", light],
]) {
  const surfaces = {
    "фон страницы": t["page-bg"],
    "ink-950": t["color-ink-950"],
    "ink-900": t["color-ink-900"],
    "ink-850": t["color-ink-850"],
  };
  // Текстовые ступени: 500 -- самая светлая из тех, что несут подписи.
  for (const step of [500, 400, 300, 200, 100, 50]) {
    for (const [sn, s] of Object.entries(surfaces)) check(name, `ink-${step} на ${sn}`, t[`color-ink-${step}`], s);
  }
  // Акцентный красный -- ровно там, где он встречается в разметке: 300 и 400
  // подписями и иконками на обычных поверхностях, 200 и 300 -- на подложках
  // алертов и бейджей (bg-brand-900/30..40).
  const alert = over(t["color-brand-900"], t["color-ink-900"], 0.3);
  for (const step of [300, 400]) {
    check(name, `brand-${step} на фоне страницы`, t[`color-brand-${step}`], t["page-bg"]);
    check(name, `brand-${step} на ink-900`, t[`color-brand-${step}`], t["color-ink-900"]);
  }
  for (const step of [200, 300]) {
    check(name, `brand-${step} на подложке алерта`, t[`color-brand-${step}`], alert);
  }
  // Белый на красных заливках -- кнопки, активные пункты меню, бейджи.
  for (const step of [500, 600]) check(name, `белый на brand-${step}`, "#ffffff", t[`color-brand-${step}`]);
}

if (failures.length) {
  console.error("\nНе проходит WCAG AA:\n" + failures.join("\n"));
  process.exit(1);
}
console.log("\nВсе пары проходят WCAG AA (4.5:1).");
