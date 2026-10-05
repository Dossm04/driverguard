import type { ScoreZone } from "@/lib/api";
import { cn } from "@/lib/utils";

const ZONE_VAR: Record<ScoreZone, string> = {
  ok: "--ok",
  warn: "--warn",
  danger: "--danger",
};

/** Кольцо Score как в эталоне: conic-gradient цветом зоны, число внутри. */
export function ScoreRing({
  value,
  zone,
  size = 64,
  className,
}: {
  value: number;
  zone: ScoreZone;
  size?: number;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  const color = `rgb(var(${ZONE_VAR[zone]}))`;
  return (
    <div
      role="img"
      aria-label={`Score ${value}`}
      className={cn("grid flex-none place-items-center rounded-full", className)}
      style={{
        width: size,
        height: size,
        background: `conic-gradient(${color} calc(${pct} * 1%), rgb(var(--line)) 0)`,
      }}
    >
      <b
        className="num grid place-items-center rounded-full bg-card font-extrabold"
        style={{
          width: size - 14,
          height: size - 14,
          fontSize: Math.round(size * 0.27),
          color,
        }}
      >
        {value}
      </b>
    </div>
  );
}
