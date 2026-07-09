/** @type {import('tailwindcss').Config} */
import generated from './generated/tailwind.partial.js'

export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      screens: {
        '2xl': '1920px',
      },
      ...generated,
    },
  },
  plugins: [],
}
