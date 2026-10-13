import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark' | 'system';

const key = 'treasurypilot.theme';

function stored(): Theme {
  try {
    const value = window.localStorage.getItem(key);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

function apply(theme: Theme) {
  const dark =
    theme === 'dark' ||
    (theme === 'system' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
}

export function initTheme() {
  apply(stored());
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(stored);
  useEffect(() => apply(theme), [theme]);
  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      if (next === 'system') window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, next);
    } catch {
      /* preference only */
    }
  }, []);
  return { theme, setTheme };
}
