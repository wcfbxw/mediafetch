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
        ink: "#121A2A",
        cloud: "#F4F7FB",
        cobalt: {
          50: "#EFF6FF",
          100: "#DBEAFE",
          500: "#2F6FEB",
          600: "#2458C6",
          700: "#1E469A"
        },
        mint: "#20B486"
      },
      boxShadow: {
        soft: "0 18px 55px rgba(23, 42, 78, 0.10)"
      }
    },
  },
  plugins: [],
};

export default config;
