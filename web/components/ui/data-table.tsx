import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: React.ReactNode;
  className?: string;
  render: (row: T) => React.ReactNode;
}

/** Универсальная таблица дизайн-системы: узкие капс-заголовки, hover строк. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  className,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  empty?: React.ReactNode;
  className?: string;
}) {
  useLangVersion();
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "border-b border-line px-2.5 py-2 text-left text-[11px] font-bold uppercase tracking-wide text-mut",
                  c.className,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-2.5 py-8 text-center text-mut">
                {empty ?? t("Данных нет")}
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              role={onRowClick ? "link" : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onRowClick(row);
                      }
                    }
                  : undefined
              }
              className={cn(
                "border-b border-line/60 last:border-b-0 hover:bg-cardh",
                onRowClick && "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              )}
            >
              {columns.map((c) => (
                <td key={c.key} className={cn("px-2.5 py-2.5 align-middle", c.className)}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
