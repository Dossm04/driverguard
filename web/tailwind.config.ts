import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Токены DriverGuard (RGB-триплеты в globals.css → работают прозрачности /15)
        page: "rgb(var(--bg) / <alpha-value>)",
        sidebar: "rgb(var(--sidebar) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        cardh: "rgb(var(--card-hover) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        txt: "rgb(var(--txt) / <alpha-value>)",
        mut: "rgb(var(--mut) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        offline: "rgb(var(--offline) / <alpha-value>)",
        onaccent: "rgb(var(--onaccent) / <alpha-value>)",
      },
      borderRadius: {
        // Радиусы дизайн-системы: карточки 16px, кнопки 12px
        card: "16px",
        btn: "12px",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
export default config;
