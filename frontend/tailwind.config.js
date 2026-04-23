/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ['"JetBrains Mono"', '"IBM Plex Mono"', "ui-monospace", "monospace"],
        body: ['"Inter"', "ui-sans-serif", "system-ui"],
      },
      colors: {
        vault: {
          bg: "#0b0d10",
          panel: "#11141a",
          line: "#1d222b",
          ink: "#e6e8ec",
          mute: "#7a828f",
          accent: "#d4ff3a",
          verified: "#6ee7a3",
          cautious: "#f4c77b",
          abstain: "#f28b82",
        },
      },
    },
  },
  plugins: [],
};
