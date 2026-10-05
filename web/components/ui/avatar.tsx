import { cn } from "@/lib/utils";

const palette = [
  "bg-accent/20 text-accent",
  "bg-ok/20 text-ok",
  "bg-warn/20 text-warn",
  "bg-danger/20 text-danger",
  "bg-offline/20 text-txt",
];

function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

/** Аватар с инициалами; цвет детерминирован именем. Кольцо — цветом зоны Score. */
export function Avatar({
  name,
  size = 34,
  ring,
  className,
  src,
}: {
  name: string;
  size?: number;
  ring?: "ok" | "warn" | "danger";
  className?: string;
  /** Фото водителя (presigned-ссылка); без него — инициалы */
  src?: string | null;
}) {
  const tone = palette[name.length % palette.length];
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={name}
        width={size}
        height={size}
        className={cn(
          "flex-none rounded-full object-cover",
          ring === "ok" && "ring-2 ring-ok",
          ring === "warn" && "ring-2 ring-warn",
          ring === "danger" && "ring-2 ring-danger",
          className,
        )}
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className={cn(
        "grid flex-none place-items-center rounded-full font-bold",
        tone,
        ring === "ok" && "ring-2 ring-ok",
        ring === "warn" && "ring-2 ring-warn",
        ring === "danger" && "ring-2 ring-danger",
        className,
      )}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}
      aria-label={name}
    >
      {initials(name)}
    </div>
  );
}
