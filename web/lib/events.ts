/* Справочник типов событий (правило 4 CLAUDE.md): названия, иконки,
   закреплённые категориальные цвета графиков. */

import {
  BatteryLow,
  CameraOff,
  ChevronsDown,
  Cigarette,
  EyeOff,
  Gauge,
  Moon,
  OctagonAlert,
  ShieldOff,
  Siren,
  Smartphone,
  type LucideIcon,
} from "lucide-react";

import type { PillTone } from "@/components/ui/status-pill";
import { t, perLang } from "@/lib/i18n";

/** Пилюли статуса review — единый источник для таблицы и модалки. */
export const STATUS_PILLS: Record<string, { label: string; tone: PillTone }> = perLang(() => ({
  new: { label: t("Новое"), tone: "accent" },
  confirmed: { label: t("Подтверждено"), tone: "ok" },
  false_positive: { label: t("Ложное"), tone: "offline" },
}));

export const EVENT_LABELS: Record<string, string> = perLang(() => ({
  microsleep: t("Засыпание за рулём"),
  distraction: t("Отвлечение"),
  phone: t("Телефон за рулём"),
  smoking: t("Курение"),
  seatbelt: t("Ремень не пристёгнут"),
  speeding: t("Превышение скорости"),
  fatigue: t("Усталость (PERCLOS)"),
  head_nod: t("Клевок головой"),
  camera_sabotage: t("Саботаж камеры"),
  harsh_braking: t("Резкое торможение"),
  sos: "SOS",
}));

export const EVENT_ICONS: Record<string, LucideIcon> = {
  microsleep: Moon,
  distraction: EyeOff,
  phone: Smartphone,
  smoking: Cigarette,
  seatbelt: ShieldOff,
  speeding: Gauge,
  fatigue: BatteryLow,
  head_nod: ChevronsDown,
  camera_sabotage: CameraOff,
  harsh_braking: OctagonAlert,
  sos: Siren,
};

/** Заголовок с величиной: «Превышение скорости +42 км/ч», «Отвлечение >8 сек». */
export function eventTitle(type: string, value?: number | null): string {
  const base = EVENT_LABELS[type] ?? type;
  if (value == null) return base;
  if (type === "speeding") return t("{0} +{1} км/ч", base, Math.round(value));
  if (type === "distraction") return t("{0} >{1} сек", base, Math.round(value));
  return base;
}

/* Цвет закреплён за типом (color follows the entity) и не зависит от порядка
   в донате. Редкие типы (саботаж, торможение, SOS) — нейтральный --offline,
   всегда с подписью в легенде. */
const TYPE_SLOT: Record<string, number> = {
  microsleep: 1,
  fatigue: 2,
  speeding: 3,
  head_nod: 4,
  smoking: 5,
  phone: 6,
  distraction: 7,
  seatbelt: 8,
};

export function eventTypeColorVar(type: string): string {
  const slot = TYPE_SLOT[type];
  return slot ? `--cat-${slot}` : "--offline";
}
