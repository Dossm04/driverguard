/* Поиск без учёта алфавита: «Иванов», «Ivanov», «Иvanov» и «Сейткали» ↔ «Seitkali» совпадают.
   Кириллица (русская и казахская) сводится к латинскому «скелету», y/i и zh/j объединяются. */

const CYR: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "j", з: "z", и: "i", й: "i", к: "k", л: "l",
  м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "s",
  щ: "s", ъ: "", ы: "i", ь: "", э: "e", ю: "u", я: "a", ә: "a", ғ: "g", қ: "k", ң: "n", ө: "o", ұ: "u",
  ү: "u", һ: "h", і: "i",
};

export function fold(value: string): string {
  return value
    .toLowerCase()
    .replace(/[а-яёәғқңөұүһі]/g, (ch) => CYR[ch] ?? ch)
    .replace(/zh/g, "j")
    .replace(/kh/g, "h")
    .replace(/sh|sch/g, "s")
    .replace(/ts/g, "c")
    .replace(/y/g, "i")
    .replace(/[^a-z0-9]+/g, "");
}

/** Есть ли запрос в строке (пустой запрос — совпадает со всем). */
export function matches(haystack: string, query: string): boolean {
  const q = fold(query);
  return !q || fold(haystack).includes(q);
}
