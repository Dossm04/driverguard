import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import { plural } from "@/lib/i18n";

/** Объединяет классы Tailwind с корректным разрешением конфликтов */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Склонение: pluralRu(2, "устройство", "устройства", "устройств") — с учётом языка интерфейса. */
export function pluralRu(n: number, one: string, few: string, many: string): string {
  return plural(n, one, few, many);
}
