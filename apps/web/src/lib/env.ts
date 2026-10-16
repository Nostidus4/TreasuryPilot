/** The in-memory API (src/mocks) stands in until VITE_API_URL points at a real one. */
export const mockApiEnabled =
  import.meta.env.VITE_API_MOCK !== 'false' && !import.meta.env.VITE_API_URL;

export const isTest = import.meta.env.MODE === 'test';

/** The one recordable scenario this build knows (docs/demo). */
export const DEMO_SCENARIO_ID = 'TP-DEMO-7M30-01';

const demoFlagKey = 'treasurypilot.demo-scenario';
const mockSessionKey = 'treasurypilot.mock-session';

/**
 * The recordable demo profile. It only exists on top of the mock API: a build with a real API
 * never enables it, whatever the env, the URL or storage say. It is on when the build sets
 * `VITE_DEMO_SCENARIO`, when `?demo=TP-DEMO-7M30-01` was opened once in this browser (the flag
 * is kept in localStorage; `?demo=off` or the Director's "Exit demo" clears it), or on the
 * Director deep link, so a statically hosted build can switch it on at runtime.
 */
export function demoScenarioEnabled(): boolean {
  if (!mockApiEnabled) return false;
  // Unit tests keep the default dataset even when CI builds with the demo env var.
  if (!isTest && import.meta.env.VITE_DEMO_SCENARIO === DEMO_SCENARIO_ID)
    return true;
  try {
    if (
      window.location.pathname.replace(/\/+$/, '').endsWith('/demo/director')
    ) {
      return true;
    }
    return window.localStorage.getItem(demoFlagKey) === DEMO_SCENARIO_ID;
  } catch {
    return false;
  }
}

/** Reads `?demo=` on load: the scenario id turns the profile on, `off` turns it off. */
export function rememberDemoFromUrl(search: string): void {
  if (!mockApiEnabled) return;
  const value = new URLSearchParams(search).get('demo');
  try {
    if (value === DEMO_SCENARIO_ID) {
      window.localStorage.setItem(demoFlagKey, DEMO_SCENARIO_ID);
    } else if (value === 'off') {
      exitDemoScenario();
    }
  } catch {
    /* the env flag still works */
  }
}

/** Leaves demo mode: the next load shows the default mock app again. */
export function exitDemoScenario(): void {
  try {
    window.localStorage.removeItem(demoFlagKey);
    // The demo signs in as a Northstar user; the default app must not inherit that session.
    window.sessionStorage.removeItem(mockSessionKey);
  } catch {
    /* nothing stored */
  }
}
