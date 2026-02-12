/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './context/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      spacing: {
        '120': '30rem',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'slide-in-from-bottom': 'slideInFromBottom 0.3s ease-out',
        'slide-in-from-bottom-2': 'slideInFromBottom2 0.4s ease-out',
        'in': 'in 0.2s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideInFromBottom: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideInFromBottom2: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        in: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
    },
  },
  plugins: [],
  safelist: [
    // Color classes for dynamic usage
    'text-red-600', 'text-red-400', 'bg-red-100', 'bg-red-900/30',
    'text-orange-600', 'text-orange-400', 'bg-orange-100', 'bg-orange-900/30',
    'text-green-600', 'text-green-400', 'bg-green-100', 'bg-green-900/30',
    'text-blue-600', 'text-blue-400', 'bg-blue-100', 'bg-blue-900/30',
    'text-purple-600', 'text-purple-400', 'bg-purple-100', 'bg-purple-900/30',
    'text-emerald-600', 'text-emerald-400', 'bg-emerald-100', 'bg-emerald-900/30',
    'hover:border-red-300', 'hover:border-orange-300', 'hover:border-green-300',
    'hover:border-blue-300', 'hover:border-purple-300', 'hover:border-emerald-300',
    'dark:hover:border-red-600', 'dark:hover:border-orange-600', 'dark:hover:border-green-600',
    'dark:hover:border-blue-600', 'dark:hover:border-purple-600', 'dark:hover:border-emerald-600',
  ],
}
