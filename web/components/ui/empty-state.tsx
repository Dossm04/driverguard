import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Пустое состояние экрана: иконка, заголовок, описание, действие. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-card border border-dashed border-line bg-card px-6 py-14 text-center",
        className,
      )}
    >
      <div className="grid h-12 w-12 place-items-center rounded-full bg-accent/10 text-accent">
        <Icon size={22} />
      </div>
      <h3 className="mt-1 text-[15px] font-bold">{title}</h3>
      {description && <p className="max-w-sm text-sm text-mut">{description}</p>}
      {action}
    </div>
  );
}
