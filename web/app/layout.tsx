import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "./providers";

// Шрифт лежит в проекте, а не качается с Google при сборке.
// С next/font/google `npm run build` падает без интернета — а `make tunnel`
// пересобирает панель прямо перед показом, когда сеть в зале может лечь.
// InterVariable включает кириллицу; лицензия SIL OFL — app/fonts/Inter-LICENSE.txt.
const inter = localFont({
  src: "./fonts/InterVariable.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DriverGuard",
  description: "Fleet Safety — панель координатора и приложение водителя",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "DriverGuard" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

/* Цвет строки состояния PWA — --bg обеих тем (единственное место с буквальными цветами,
   как и manifest.ts: браузер не читает CSS-переменные из мета-тегов) */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0F1523" },
    { media: "(prefers-color-scheme: light)", color: "#F4F6FB" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // suppressHydrationWarning: next-themes ставит класс темы на <html> до гидратации
  return (
    <html lang="ru" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
