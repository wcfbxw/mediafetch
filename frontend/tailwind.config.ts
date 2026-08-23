import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        ink: "#101729",
        cloud: "#F6F7FB",
        cobalt: {
          50: "#EEF2FF",
          100: "#E0E7FF",
          500: "#5B5FEF",
          600: "#4B4FD8",
          700: "#3F42B7"
        },
        mint: "#18B981",
        signal: "#C8F45D"
      },
      boxShadow: {
        soft: "0 22px 70px rgba(23, 31, 56, 0.10)",
        panel: "0 1px 0 rgba(255,255,255,.8) inset, 0 24px 70px rgba(23,31,56,.08)"
      }
    },
  },
  plugins: [],
};

export default config;
