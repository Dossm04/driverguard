import type { MetadataRoute } from "next";

/* PWA водителя (APP-*, ТЗ 5.4): манифест не умеет CSS-переменные, поэтому здесь
   единственное место с цветами темы буквально (--bg тёмной темы, docs/decisions.md). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DriverGuard — водитель",
    short_name: "DriverGuard",
    description: "Смена, чек-лист, мой Score, SOS и обучение для водителя",
    lang: "ru",
    start_url: "/driver",
    scope: "/driver",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0F1523",
    theme_color: "#0F1523",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
