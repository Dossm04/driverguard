import { cn } from "@/lib/utils";

/** Карточка-секция: заголовок + подзаголовок + правый слот (пилюля/кнопки). */
export function SectionCard({
  title,
  subtitle,
  action,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-card border border-line bg-card p-4", className)}>
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-bold leading-5">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-mut">{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
