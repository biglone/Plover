/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f4efe5",
        ink: "#1f2937",
        moss: "#35564a",
        clay: "#ca6f47",
        wheat: "#f6d7a7",
        mist: "#dce7dd"
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        body: ["'IBM Plex Sans'", "sans-serif"]
      },
      boxShadow: {
        panel: "0 18px 45px rgba(53, 86, 74, 0.14)"
      }
    }
  },
  plugins: []
};

