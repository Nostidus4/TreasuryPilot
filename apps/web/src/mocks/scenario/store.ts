/**
 * The stateful half of the demo scenario: persistence, playback timers and the bridge between
 * the main window and the Director window. The engine stays pure; everything with a side
 * effect lives here.
 *
 * Only the main window runs playback and changes state. The Director window is a follower: it
 * validates a command against the shared snapshot, sends it over BroadcastChannel, and shows
 * whatever the main window persists (localStorage + `storage` events).
 */
import {
  ActionError,
  applyAll,
  directorAction,
  fixture,
  initialState,
  nextAuto,
  type DemoRole,
  type DirectorAction,
  type ScenarioEvent,
  type ScenarioState,
} from './engine';

const SNAPSHOT_KEY = `treasurypilot.demo.${fixture.scenarioId}.snapshot`;
const CHANNEL_NAME = `treasurypilot.demo.${fixture.scenarioId}`;
export const DEMO_CHANGED_EVENT = 'treasurypilot:demo-changed';
const ACK_TIMEOUT_MS = 2000;

interface Command {
  kind: 'command';
  commandId: string;
  action: DirectorAction;
}
interface Ack {
  kind: 'ack';
  commandId: string;
  ok: boolean;
  code?: string;
  message?: string;
  noop?: boolean;
}

export interface DirectorResult {
  ok: boolean;
  noop: boolean;
  message: string;
}

let state: ScenarioState = initialState();
let timeScale = 1;
let started = false;
let channel: BroadcastChannel | null = null;
let timer: { key: string; handle: ReturnType<typeof setTimeout> } | null = null;
const listeners = new Set<(next: ScenarioState) => void>();
const pendingAcks = new Map<string, (ack: Ack) => void>();

/** The Director route is a follower; every other window is the main window. */
export function isFollower(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.location.pathname.replace(/\/+$/, '').endsWith('/demo/director')
  );
}

export function getScenario(): ScenarioState {
  return state;
}

export function subscribeScenario(listener: (next: ScenarioState) => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Tests set 0 so every scheduled transition fires on the next tick. */
export function setScenarioTimeScale(scale: number) {
  timeScale = scale;
}

function readSnapshot(): ScenarioState | null {
  try {
    const raw = window.localStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ScenarioState;
    if (parsed.version !== 1 || parsed.scenarioId !== fixture.scenarioId) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeSnapshot() {
  try {
    window.localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(state));
  } catch {
    /* the scenario still runs in memory for this window */
  }
}

function notify() {
  for (const listener of listeners) listener(state);
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(DEMO_CHANGED_EVENT));
  }
}

function clearTimer() {
  if (timer) clearTimeout(timer.handle);
  timer = null;
}

/** Schedules the next automatic transition, if any. A callback from an older run is dropped. */
function pump() {
  if (isFollower()) return;
  const auto = nextAuto(state);
  const key = auto ? `${state.runId}:${auto.events[0].id}` : null;
  if (timer && timer.key === key) return;
  clearTimer();
  if (!auto || !key) return;
  const runId = state.runId;
  timer = {
    key,
    handle: setTimeout(() => {
      timer = null;
      if (state.runId !== runId) return;
      commit(applyAll(state, auto.events));
    }, auto.delayMs * timeScale),
  };
}

function commit(next: ScenarioState) {
  if (next !== state) {
    state = next;
    writeSnapshot();
    notify();
  }
  pump();
}

/** Starts the scenario in this window: restore the snapshot, resume playback, open the bridge. */
export function startScenario() {
  if (started) return;
  started = true;
  state = readSnapshot() ?? initialState();
  if (!isFollower()) writeSnapshot();
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
      if (event.key !== SNAPSHOT_KEY) return;
      const next = readSnapshot();
      if (!next) return;
      // A follower mirrors the main window; the main window only takes a newer run.
      if (isFollower() || next.runId > state.runId) {
        state = next;
        notify();
        pump();
      }
    });
    if (isFollower()) {
      // storage events can be missed by a window that was in the background.
      window.setInterval(() => {
        const next = readSnapshot();
        if (next && JSON.stringify(next) !== JSON.stringify(state)) {
          state = next;
          notify();
        }
      }, 1000);
    }
  }
  if (typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (message: MessageEvent<Command | Ack>) => {
      const data = message.data;
      if (data.kind === 'ack') {
        pendingAcks.get(data.commandId)?.(data);
        return;
      }
      if (isFollower()) return;
      handleCommand(data);
    };
  }
  notify();
  pump();
}

function handleCommand(command: Command) {
  let ack: Ack;
  try {
    const result = runDirectorLocal(command.action);
    ack = { kind: 'ack', commandId: command.commandId, ok: true, ...result };
  } catch (error) {
    ack = {
      kind: 'ack',
      commandId: command.commandId,
      ok: false,
      code: error instanceof ActionError ? error.code : 'ERROR',
      message: error instanceof Error ? error.message : 'The command failed.',
    };
  }
  channel?.postMessage(ack);
}

/* ───────────── Main-window mutations ───────────── */

export function dispatchEvents(events: ScenarioEvent[]) {
  commit(applyAll(state, events));
}

export function resetScenario() {
  clearTimer();
  // A new run: callbacks scheduled by the old one find a different runId and do nothing.
  state = { ...initialState(state.runId + 1), role: 'FINANCE' };
  writeSnapshot();
  notify();
  pump();
}

export function setRole(role: DemoRole) {
  if (state.role === role) return;
  commit({ ...state, role });
}

function runDirectorLocal(action: DirectorAction): {
  noop: boolean;
  message: string;
} {
  if (action === 'RESET_DAY_D') {
    resetScenario();
    return { noop: false, message: `Scenario reset (run ${state.runId}).` };
  }
  const result = directorAction(state, action);
  if (result.events.length > 0) dispatchEvents(result.events);
  else pump();
  return {
    noop: Boolean(result.noop),
    message: result.message ?? `${action} applied.`,
  };
}

/**
 * Runs a Director action. The main window applies it directly; the Director window checks the
 * guard on the shared snapshot first, then asks the main window and waits for its answer.
 */
export async function runDirector(
  action: DirectorAction,
): Promise<DirectorResult> {
  if (!isFollower()) {
    const result = runDirectorLocal(action);
    return { ok: true, ...result };
  }
  if (action !== 'RESET_DAY_D') directorAction(state, action);
  if (!channel) {
    throw new ActionError(
      'NO_CHANNEL',
      'BroadcastChannel is not available in this browser.',
      503,
    );
  }
  const commandId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const ack = await new Promise<Ack>((resolve, reject) => {
    const handle = setTimeout(() => {
      pendingAcks.delete(commandId);
      reject(
        new ActionError(
          'NO_MAIN_WINDOW',
          'No main window answered. Open the product in another window of this browser first.',
          503,
        ),
      );
    }, ACK_TIMEOUT_MS);
    pendingAcks.set(commandId, (value) => {
      clearTimeout(handle);
      pendingAcks.delete(commandId);
      resolve(value);
    });
    channel!.postMessage({
      kind: 'command',
      commandId,
      action,
    } satisfies Command);
  });
  if (!ack.ok) {
    throw new ActionError(
      ack.code ?? 'ERROR',
      ack.message ?? 'The command failed.',
    );
  }
  return { ok: true, noop: Boolean(ack.noop), message: ack.message ?? '' };
}

/** Test helper: forget everything, including the persisted snapshot. */
export function resetScenarioForTests() {
  clearTimer();
  started = false;
  channel?.close();
  channel = null;
  listeners.clear();
  try {
    window.localStorage.removeItem(SNAPSHOT_KEY);
  } catch {
    /* nothing stored */
  }
  state = initialState();
}
