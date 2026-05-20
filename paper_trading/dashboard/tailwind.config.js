/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#0a0a0f',
          50: '#0d0d14',
          100: '#111118',
          200: '#16161e',
        },
        border: {
          DEFAULT: '#1e1e2a',
          50: '#252535',
          100: '#2a2a3a',
        },
      },
      animation: {
        'pulse-subtle': 'pulse-subtle 2s ease-in-out infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'slide-up': 'slide-up 0.3s ease-out',
        'fade-in': 'fade-in 0.3s ease-out',
      },
      keyframes: {
        'pulse-subtle': {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        'glow': {
          '0%': { boxShadow: '0 0 20px rgba(52, 211, 153, 0.1)' },
          '100%': { boxShadow: '0 0 40px rgba(52, 211, 153, 0.2)' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
