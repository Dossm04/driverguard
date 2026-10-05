"use client";

/* Recharts задаёт fill SVG-атрибутом, где var() не работает, — поэтому резолвим
   CSS-переменные в конкретные rgb(). Следим за классом <html> через
   MutationObserver: эффект провайдера next-themes меняет класс ПОСЛЕ эффектов
   потомков, поэтому подписка на resolvedTheme читала бы старую тему
   (правило 1 CLAUDE.md: графики переключаются вместе с темой). */

import { useEffect, useState } from "react";

export function useTokenColors(vars: string[]): Record<string, string> | null {
  const [colors, setColors] = useState<Record<string, string> | null>(null);
  const key = vars.join(",");

  useEffect(() => {
    const read = () => {
      const style = getComputedStyle(document.documentElement);
      const result: Record<string, string> = {};
      for (const name of key.split(",")) {
        const triplet = style.getPropertyValue(name).trim();
        result[name] = triplet ? `rgb(${triplet})` : "";
      }
      setColors(result);
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, [key]);

  return colors;
}
