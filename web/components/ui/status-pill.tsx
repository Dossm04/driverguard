import { cn } from "@/lib/utils";

export type PillTone = "ok" | "warn" | "danger" | "accent" | "offline";

const tones: Record<PillTone, string> = {
  ok: "bg-ok/15 text-ok",
  warn: "bg-warn/15 text-warn",
  danger: "bg-danger/15 text-danger",
  accent: "bg-accent/15 text-accent",
  offline: "bg-offline/15 text-offline",
};

/** Статус-пилюля: тонированный фон 15% + цветной текст (дизайн-система). */
export function StatusPill({
  tone,
  children,
  className,
}: {
  tone: PillTone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
