/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: { colors: { ink: { 950: "#0b0f14", 900: "#10161d", 800: "#161e27", 700: "#1f2933", 600: "#2b3744" }, leaf: { 400: "#4ade80", 500: "#22c55e", 600: "#16a34a" } },
    fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"], mono: ["ui-monospace", "Cascadia Code", "Consolas", "monospace"] } } },
  plugins: [],
};
