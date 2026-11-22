import forms from '@tailwindcss/forms'

/**
 * Theme merged from the three Google Stitch exports (design/stitch-exports/*).
 * Values are copied from each export's inline tailwind.config so the
 * Stitch class names render the same way here.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#4f46e5', hover: '#4338ca', light: '#eef2ff' },
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
        },
        'brand-slate': {
          50: '#f8fafc', 100: '#f1f5f9', 200: '#e2e8f0', 300: '#cbd5e1', 400: '#94a3b8',
          500: '#64748b', 600: '#475569', 700: '#334155', 800: '#1e293b', 900: '#0f172a',
        },
        slate: { 25: '#fcfdfe' },
        'live-red': '#e11d48',
        surface: {
          DEFAULT: '#ffffff',
          ground: '#f8fafc',
          subtle: '#f1f5f9',
          border: '#e2e8f0',
          borderStrong: '#cbd5e1',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        '2xs': '0 1px 1px rgba(15, 23, 42, 0.03)',
        xs: '0 1px 2px rgba(15, 23, 42, 0.04)',
        card: '0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)',
        'card-hover': '0 10px 25px -3px rgba(15, 23, 42, 0.08), 0 4px 6px -4px rgba(15, 23, 42, 0.04)',
        glow: '0 0 25px -5px rgba(99, 102, 241, 0.2)',
        'glow-indigo': '0 0 20px -3px rgba(99, 102, 241, 0.25)',
        subtle: '0 4px 20px -2px rgba(15, 23, 42, 0.04)',
      },
      keyframes: {
        'pulse-red': {
          '0%': { transform: 'scale(0.95)', boxShadow: '0 0 0 0 rgba(225, 29, 72, 0.7)' },
          '70%': { transform: 'scale(1)', boxShadow: '0 0 0 5px rgba(225, 29, 72, 0)' },
          '100%': { transform: 'scale(0.95)', boxShadow: '0 0 0 0 rgba(225, 29, 72, 0)' },
        },
        'fade-in': { from: { opacity: 0 }, to: { opacity: 1 } },
        'pop-in': {
          from: { opacity: 0, transform: 'translateY(6px) scale(0.98)' },
          to: { opacity: 1, transform: 'translateY(0) scale(1)' },
        },
        'slide-in-right': { from: { transform: 'translateX(100%)' }, to: { transform: 'translateX(0)' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        flash: { '0%': { backgroundColor: 'rgba(16, 185, 129, 0.18)' }, '100%': { backgroundColor: 'transparent' } },
      },
      animation: {
        'pulse-red': 'pulse-red 2s infinite',
        'fade-in': 'fade-in 150ms ease-out',
        'pop-in': 'pop-in 180ms cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in-right': 'slide-in-right 220ms cubic-bezier(0.16, 1, 0.3, 1)',
        flash: 'flash 1.2s ease-out',
      },
    },
  },
  plugins: [forms],
}
