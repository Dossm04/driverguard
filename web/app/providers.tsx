"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { isDriverPath } from "@/lib/api";
import { useHtmlLang } from "@/lib/i18n/react";

/* Тема панели и тема PWA водителя хранятся отдельно (storageKey по области), иначе
   переключение в одном приложении меняло бы вид другого в том же браузере. */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );
  const pathname = usePathname();
  const area = isDriverPath(pathname) ? "driver" : "staff";
  // Язык берётся из localStorage только в браузере: рендерим дерево после монтирования,
  // чтобы серверный HTML (ru) не расходился с клиентским (kk/en) при гидратации.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useHtmlLang();
  return (
    <ThemeProvider
      key={area}
      attribute="class"
      defaultTheme="dark"
      enableSystem
      storageKey={area === "driver" ? "theme-driver" : "theme"}
    >
      <QueryClientProvider client={queryClient}>{mounted ? children : null}</QueryClientProvider>
    </ThemeProvider>
  );
}
