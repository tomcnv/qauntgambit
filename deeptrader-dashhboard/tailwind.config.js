import { fontFamily } from "tailwindcss/defaultTheme";
import animate from "tailwindcss-animate";
import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: {
        "2xl": "1440px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border) / <alpha-value>)",
        input: "hsl(var(--input) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        primary: {
          DEFAULT: "hsl(var(--primary) / <alpha-value>)",
          foreground: "hsl(var(--primary-foreground) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary) / <alpha-value>)",
          foreground: "hsl(var(--secondary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted) / <alpha-value>)",
          foreground: "hsl(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        card: {
          DEFAULT: "hsl(var(--card) / <alpha-value>)",
          foreground: "hsl(var(--card-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "hsl(var(--popover) / <alpha-value>)",
          foreground: "hsl(var(--popover-foreground) / <alpha-value>)",
        },
        positive: "hsl(var(--positive) / <alpha-value>)",
        negative: "hsl(var(--negative) / <alpha-value>)",
        warning: "hsl(var(--warning) / <alpha-value>)",
        glow: "hsl(var(--glow) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["InterVariable", ...fontFamily.sans],
        display: ["Space Grotesk", ...fontFamily.sans],
      },
      keyframes: {
        "fade-in": {
          from: { opacity: 0, transform: "translateY(6px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(37, 99, 235, 0.35)" },
          "50%": { boxShadow: "0 0 30px 4px rgba(37, 99, 235, 0.45)" },
        },
        "slow-pan": {
          "0%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-12px)" },
          "100%": { transform: "translateY(0px)" },
        },
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "fade-in": "fade-in 400ms ease-out",
        "pulse-glow": "pulse-glow 2.5s ease-in-out infinite",
        "slow-pan": "slow-pan 8s ease-in-out infinite",
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
      boxShadow: {
        elevated: "0 30px 120px -50px rgba(2,6,23,0.8)",
        border: "0 0 0 1px rgba(255,255,255,0.04)",
      },
      backgroundImage: {
        "noise": "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.07) 1px, transparent 0)",
      },
    },
  },
  plugins: [
    animate,
    typography,
    // Add light: variant for .light class
    function ({ addVariant }) {
      addVariant('light', '.light &');
    },
    function ({ addBase }) {
      addBase({
        ":root": {
          "--background": "224 50% 8%",
          "--foreground": "210 40% 98%",
          "--card": "228 40% 12%",
          "--card-foreground": "210 40% 98%",
          "--popover": "228 40% 12%",
          "--popover-foreground": "210 40% 98%",
          "--primary": "199 89% 48%",
          "--primary-foreground": "0 0% 100%",
          "--secondary": "217 32% 18%",
          "--secondary-foreground": "210 40% 98%",
          "--muted": "220 30% 15%",
          "--muted-foreground": "215 20% 65%",
          "--accent": "199 89% 48%",
          "--accent-foreground": "0 0% 100%",
          "--destructive": "0 62% 55%",
          "--destructive-foreground": "210 40% 98%",
          "--border": "217 32% 18%",
          "--input": "217 32% 18%",
          "--ring": "199 89% 48%",
          "--radius": "0.75rem",
          "--positive": "142 71% 45%",
          "--negative": "0 72% 50%",
          "--warning": "38 92% 50%",
          "--glow": "199 89% 48%",
          "--bg-gradient": "none",
        },
        ".light": {
          "--background": "220 20% 96%",
          "--foreground": "222 47% 11%",
          "--card": "0 0% 100%",
          "--card-foreground": "222 47% 11%",
          "--popover": "0 0% 100%",
          "--popover-foreground": "222 47% 11%",
          "--primary": "219 100% 50%",
          "--primary-foreground": "0 0% 100%",
          "--secondary": "217 24% 94%",
          "--secondary-foreground": "222 47% 11%",
          "--muted": "215 16% 92%",
          "--muted-foreground": "222 16% 38%",
          "--accent": "219 100% 50%",
          "--accent-foreground": "0 0% 100%",
          "--destructive": "0 70% 50%",
          "--destructive-foreground": "0 0% 100%",
          "--border": "220 18% 86%",
          "--input": "220 18% 86%",
          "--ring": "219 100% 50%",
          "--positive": "150 55% 40%",
          "--negative": "0 65% 45%",
          "--warning": "38 92% 46%",
          "--glow": "219 100% 50%",
          "--bg-gradient":
            "radial-gradient(circle at 20% 15%, rgba(37, 99, 235, 0.12), transparent 50%), radial-gradient(circle at 80% 0%, rgba(59, 130, 246, 0.1), transparent 45%), radial-gradient(circle at 50% 80%, rgba(56, 189, 248, 0.08), transparent 55%)",
        },
      });
    },
  ],
};

