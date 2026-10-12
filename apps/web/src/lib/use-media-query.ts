import { useEffect, useState } from 'react';

/** `true` when the query matches. Defaults to desktop where matchMedia is missing. */
export function useMediaQuery(query: string): boolean {
  const supported =
    typeof window !== 'undefined' && typeof window.matchMedia === 'function';
  const [matches, setMatches] = useState(() =>
    supported ? window.matchMedia(query).matches : true,
  );
  useEffect(() => {
    if (!supported) return;
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query, supported]);
  return matches;
}
