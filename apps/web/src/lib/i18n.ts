import i18next from 'i18next';

/**
 * Strings are externalized gettext-style: the English text is the key, so the
 * source stays readable and a translator adds `vi` / `zh` resources later
 * (NFR-UX-05, M16-D8). English is the only language in M1.
 */
void i18next.init({
  lng: 'en',
  fallbackLng: 'en',
  keySeparator: false,
  nsSeparator: false,
  resources: { en: { translation: {} } },
  interpolation: { escapeValue: false },
});

export function t(
  text: string,
  values?: Record<string, string | number>,
): string {
  return i18next.t(text, values);
}
