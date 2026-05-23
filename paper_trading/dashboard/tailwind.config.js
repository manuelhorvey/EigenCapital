/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        display: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
      colors: {
        surface: {
          DEFAULT: '#08090c',
          50: '#0c0d12',
          100: '#111318',
          200: '#161820',
        },
        border: {
          DEFAULT: '#1a1d28',
          50: '#222633',
          100: '#2a3040',
        },
        'gov-green': {
          DEFAULT: '#34d399',
          muted: 'rgba(52, 211, 153, 0.12)',
          muted2: 'rgba(52, 211, 153, 0.06)',
        },
        'gov-yellow': {
          DEFAULT: '#fbbf24',
          muted: 'rgba(251, 191, 36, 0.12)',
          muted2: 'rgba(251, 191, 36, 0.06)',
        },
        'gov-red': {
          DEFAULT: '#f87171',
          muted: 'rgba(248, 113, 113, 0.12)',
          muted2: 'rgba(248, 113, 113, 0.06)',
        },
        'gov-init': {
          DEFAULT: '#64748b',
          muted: 'rgba(100, 116, 139, 0.12)',
          muted2: 'rgba(100, 116, 139, 0.06)',
        },
        'accent-emerald': '#34d399',
        'accent-blue': '#60a5fa',
        'accent-purple': '#a78bfa',
        'accent-amber': '#fbbf24',
        'accent-indigo': '#818cf8',
        'accent-pink': '#f472b6',
      },
      boxShadow: {
        panel: '0 1px 0 rgba(255,255,255,0.04) inset, 0 4px 24px rgba(0,0,0,0.35)',
        card: '0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 32px rgba(0,0,0,0.4)',
        'glow-emerald': '0 0 24px rgba(52, 211, 153, 0.15)',
        'glow-blue': '0 0 24px rgba(96, 165, 250, 0.12)',
        'glow-amber': '0 0 24px rgba(251, 191, 36, 0.1)',
        'inner-subtle': 'inset 0 1px 0 rgba(255,255,255,0.03)',
        'lift': '0 8px 40px rgba(0,0,0,0.5)',
      },
      borderRadius: {
        DEFAULT: '6px',
        lg: '8px',
        xl: '10px',
        '2xl': '12px',
      },
      spacing: {
        18: '4.5rem',
      },
      transitionDuration: {
        '250': '250ms',
      },
      animation: {
        'pulse-subtle': 'pulse-subtle 2s ease-in-out infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'slide-up': 'slide-up 0.35s ease-out',
        'fade-in': 'fade-in 0.4s ease-out',
        'shimmer': 'shimmer 2s infinite',
      },
      keyframes: {
        'pulse-subtle': {
          '0%, 100%': { opacity: '0.5' },
          '50%': { opacity: '1' },
        },
        'glow': {
          '0%': { boxShadow: '0 0 16px rgba(52, 211, 153, 0.08)' },
          '100%': { boxShadow: '0 0 32px rgba(52, 211, 153, 0.18)' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(6px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
}
