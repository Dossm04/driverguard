/* Силуэт-подсказка для кадра чек-листа (APP-3): грузовик спереди/сзади/сбоку, шина, лобовое, низ. */

export function Silhouette({ slot, className }: { slot: string; className?: string }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 3,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeDasharray: "8 6",
  };
  return (
    <svg viewBox="0 0 200 120" className={className} aria-hidden="true">
      {slot === "front_lights" && (
        <g {...common}>
          <rect x="40" y="20" width="120" height="70" rx="10" />
          <rect x="52" y="30" width="96" height="30" rx="4" />
          <circle cx="60" cy="76" r="7" />
          <circle cx="140" cy="76" r="7" />
          <path d="M40 100h120M52 90v12M148 90v12" />
        </g>
      )}
      {slot === "rear_lights" && (
        <g {...common}>
          <rect x="30" y="16" width="140" height="80" rx="6" />
          <path d="M100 16v80M30 60h140" />
          <rect x="34" y="72" width="12" height="18" rx="2" />
          <rect x="154" y="72" width="12" height="18" rx="2" />
          <path d="M30 106h140" />
        </g>
      )}
      {(slot === "left_side" || slot === "right_side") && (
        <g {...common} transform={slot === "right_side" ? "scale(-1 1) translate(-200 0)" : undefined}>
          <path d="M10 82V40h40l14-22h52v64" />
          <rect x="116" y="26" width="76" height="56" rx="4" />
          <path d="M10 82h182" />
          <circle cx="42" cy="90" r="12" />
          <circle cx="150" cy="90" r="12" />
          <rect x="22" y="32" width="24" height="18" rx="3" />
        </g>
      )}
      {slot === "tires" && (
        <g {...common}>
          <circle cx="100" cy="60" r="46" />
          <circle cx="100" cy="60" r="22" />
          <path d="M100 14v24M100 82v24M54 60h24M122 60h24M67 27l17 17M116 76l17 17M133 27l-17 17M84 76l-17 17" />
        </g>
      )}
      {slot === "windshield" && (
        <g {...common}>
          <path d="M30 96 50 24h100l20 72z" />
          <path d="M70 96 92 40M120 40l-6 56" />
          <path d="M30 108h140" />
        </g>
      )}
      {slot === "under_engine" && (
        <g {...common}>
          <path d="M20 40h160v30H20z" />
          <circle cx="50" cy="82" r="14" />
          <circle cx="150" cy="82" r="14" />
          <path d="M70 70h60M90 92v14M110 92v14" />
          <path d="M84 108q16 8 32 0" />
        </g>
      )}
    </svg>
  );
}
