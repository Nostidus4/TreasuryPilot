import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

const token = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

const tone = (name: string) => ({
  DEFAULT: token(name),
  foreground: token(`${name}-foreground`),
  muted: token(`${name}-muted`),
  border: token(`${name}-border`),
});

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // The type scale and radii are closed sets: arbitrary values are linted out.
    fontSize: {
      xs: ['0.75rem', { lineHeight: '1rem' }],
      sm: ['0.8125rem', { lineHeight: '1.25rem' }],
      base: ['0.875rem', { lineHeight: '1.25rem' }],
      lg: ['1rem', { lineHeight: '1.5rem' }],
      xl: ['1.25rem', { lineHeight: '1.75rem', letterSpacing: '-0.01em' }],
      '2xl': ['1.5rem', { lineHeight: '2rem', letterSpacing: '-0.02em' }],
      display: ['2rem', { lineHeight: '2.5rem', letterSpacing: '-0.03em' }],
    },
    borderRadius: {
      none: '0',
      sm: '0.25rem',
      md: '0.375rem',
      lg: 'var(--radius)',
      full: '9999px',
    },
    extend: {
      fontFamily: {
        sans: [
          "'IBM Plex Sans Variable'",
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          "'Segoe UI'",
          'sans-serif',
        ],
        mono: [
          "'IBM Plex Mono'",
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'monospace',
        ],
      },
      colors: {
        background: token('background'),
        surface: {
          DEFAULT: token('surface'),
          muted: token('surface-muted'),
        },
        border: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        foreground: token('foreground'),
        muted: {
          DEFAULT: token('surface-muted'),
          foreground: token('muted-foreground'),
        },
        subtle: { foreground: token('subtle-foreground') },
        primary: {
          DEFAULT: token('primary'),
          hover: token('primary-hover'),
          foreground: token('primary-foreground'),
          muted: token('primary-muted'),
        },
        ring: token('ring'),
        overlay: token('overlay'),
        success: tone('success'),
        warning: tone('warning'),
        danger: tone('danger'),
        info: tone('info'),
        ai: tone('ai'),
        chart: {
          1: 'var(--chart-1)',
          2: 'var(--chart-2)',
          3: 'var(--chart-3)',
          4: 'var(--chart-4)',
        },
      },
      boxShadow: {
        // Only floating layers (popover, dialog, sheet) cast a shadow.
        float:
          '0 0 0 1px hsl(var(--overlay) / 0.04), 0 8px 24px -6px hsl(var(--overlay) / 0.16)',
      },
      keyframes: {
        'pulse-dot': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
      },
      animation: {
        'pulse-dot': 'pulse-dot 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [animate],
} satisfies Config;
