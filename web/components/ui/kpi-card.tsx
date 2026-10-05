import { TrendingDown, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { cn } from "@/lib/utils";

const iconTones: Record<PillTone, string> = {
  ok: "bg-ok/15 text-ok",
  warn: "bg-warn/15 text-warn",
  danger: "bg-danger/15 text-danger",
  accent: "bg-accent/15 text-accent",
  offline: "bg-offline/15 text-offline",
};

export interface KpiCardProps {
  title: string;
  icon: LucideIcon;
  iconTone: PillTone;
  value: React.ReactNode;
  /** Тренд рядом с числом: например +3 или −2 */
  trend?: { value: string; tone: "ok" | "danger" | "warn" };
  sub?: React.ReactNode;
  pill?: { label: string; tone: PillTone };
  className?: string;
}

/** KPI-карточка по Figma: заголовок, иконка в цветном круге, число, подпись, пилюля. */
export function KpiCard({
  title,
  icon: Icon,
  iconTone,
  value,
  trend,
  sub,
  pill,
  className,
}: KpiCardProps) {
  // Направление стрелки — по знаку значения; цвет (tone) — по смыслу для бизнеса
  const negative = trend ? /^\s*[-−]/.test(trend.value) : false;
  const TrendIcon = negative ? TrendingDown : TrendingUp;
  return (
    <div data-kpi={title} className={cn("rounded-card border border-line bg-card p-4", className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-medium leading-tight text-mut">{title}</div>
        <div
          className={cn(
            "grid h-9 w-9 flex-none place-items-center rounded-full",
            iconTones[iconTone],
          )}
        >
          <Icon size={18} />
        </div>
      </div>
      <div className="num mt-1 flex items-baseline gap-2 text-[26px] font-extrabold leading-8">
        {value}
        {trend && (
          <span
            className={cn(
              "num inline-flex items-center gap-0.5 text-xs font-bold",
              trend.tone === "ok" && "text-ok",
              trend.tone === "danger" && "text-danger",
              trend.tone === "warn" && "text-warn",
            )}
          >
            <TrendIcon size={14} />
            {trend.value}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className="text-xs text-mut">{sub}</div>
        {pill && <StatusPill tone={pill.tone}>{pill.label}</StatusPill>}
      </div>
    </div>
  );
}
