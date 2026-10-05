import { cn } from "@/lib/utils";

/** Скелетон загрузки на токенах темы. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-btn bg-cardh", className)} />;
}
