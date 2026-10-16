import { createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, type BrowserContext, type Page } from '@playwright/test';
import { privateKeyToAccount } from 'viem/accounts';

/**
 * Helpers for the full-stack E2E (real API + Postgres + Anvil, mock off).
 * Signing uses the public Anvil dev keys only (mnemonic "test test ... junk").
 */

const here = path.dirname(fileURLToPath(import.meta.url));
const stateDir = path.join(here, '.state');

export const rpcUrl = process.env.E2E_ANVIL_RPC_URL ?? 'http://127.0.0.1:8545';
export const ctlUrl = `http://127.0.0.1:${process.env.E2E_CTL_PORT ?? '8790'}`;
export const webOrigin = 'http://localhost:4179';

/** Public Anvil dev accounts: #0 owns every demo Safe (threshold 1). */
export const anvilKeys = {
  owner:
    '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80',
} as const;
export const ownerAccount = privateKeyToAccount(anvilKeys.owner);

export const users = {
  owner: 'owner@seed.treasurypilot.test',
  finance: 'finance@seed.treasurypilot.test',
  approver: 'approver@seed.treasurypilot.test',
} as const;

export interface StackState {
  orgId: string;
  treasuryId: string;
  module: string;
  safeT: string;
  testToken: string;
  ownerAddress: string;
}

export const stack = (): StackState =>
  JSON.parse(readFileSync(path.join(stateDir, 'stack.json'), 'utf8')) as StackState;

export async function ctl<T = Record<string, unknown>>(
  route: string,
  body: Record<string, unknown> = {},
): Promise<T> {
  const response = await fetch(`${ctlUrl}${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(`ctl ${route}: ${payload.error}`);
  return payload;
}

export async function anvil<T = unknown>(
  method: string,
  params: unknown[] = [],
): Promise<T> {
  const response = await fetch(rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  const payload = (await response.json()) as {
    result?: T;
    error?: { message: string };
  };
  if (payload.error) throw new Error(`${method}: ${payload.error.message}`);
  return payload.result as T;
}

/** Run the worker's indexer, tracker and payee activation once (no Celery beat in this stack). */
export const tick = () => ctl('/tick');

/**
 * Move time forward without waiting: Anvil `evm_increaseTime` + `evm_mine`. The API has no test
 * clock, so the control API also shifts Cooling payees' chain-time `active_from` into the
 * wall-clock frame the API and worker read.
 */
export const advanceTime = (seconds: number) =>
  ctl('/advance-time', { seconds });

const intTypes = /^u?int\d*$/;

/** Convert decimal-string integers to bigint so viem hashes them like a wallet would. */
function reviveTypedData(typed: {
  types: Record<string, Array<{ name: string; type: string }>>;
  primaryType: string;
  message: Record<string, unknown>;
  domain: Record<string, unknown>;
}) {
  const message = { ...typed.message };
  for (const field of typed.types[typed.primaryType] ?? []) {
    const value = message[field.name];
    if (intTypes.test(field.type) && value !== undefined) {
      message[field.name] = BigInt(value as string | number);
    }
  }
  const domain = { ...typed.domain };
  if (domain.chainId !== undefined)
    domain.chainId = Number(domain.chainId);
  return { ...typed, message, domain };
}

/**
 * Install an EIP-1193 `window.ethereum` backed by an Anvil dev key. Signing happens here in Node;
 * transactions go to the unlocked Anvil account. Nothing leaves the local node.
 */
export async function installWallet(context: BrowserContext) {
  const address = ownerAccount.address;
  await context.exposeFunction(
    '__tpWallet',
    async (method: string, params: unknown[]): Promise<unknown> => {
      switch (method) {
        case 'eth_requestAccounts':
        case 'eth_accounts':
          return [address];
        case 'wallet_switchEthereumChain':
          return null;
        case 'personal_sign':
          return ownerAccount.signMessage({
            message: { raw: params[0] as `0x${string}` },
          });
        case 'eth_signTypedData_v4': {
          const typed = JSON.parse(params[1] as string) as Parameters<
            typeof reviveTypedData
          >[0];
          const revived = reviveTypedData(typed);
          return ownerAccount.signTypedData(
            revived as unknown as Parameters<
              typeof ownerAccount.signTypedData
            >[0],
          );
        }
        case 'eth_sendTransaction': {
          const [tx] = params as [Record<string, unknown>];
          return anvil('eth_sendTransaction', [{ ...tx, from: address }]);
        }
        default:
          return anvil(method, params);
      }
    },
  );
  await context.addInitScript(() => {
    const w = window as unknown as {
      __tpWallet: (method: string, params: unknown[]) => Promise<unknown>;
      ethereum?: unknown;
    };
    w.ethereum = {
      isMetaMask: true,
      request: ({ method, params }: { method: string; params?: unknown[] }) =>
        w.__tpWallet(method, params ?? []),
      on: () => undefined,
      removeListener: () => undefined,
    };
  });
}

/** Sign in through the real magic-link verify page with a freshly minted single-use token. */
export async function loginAs(page: Page, email: string) {
  const { token } = await ctl<{ token: string }>('/login-token', { email });
  await page.goto(`/verify?token=${encodeURIComponent(token)}`);
  await page.waitForURL((url) => !url.pathname.startsWith('/verify'));
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies(webOrigin);
  const csrf = cookies.find((cookie) => cookie.name === 'tp_csrf')?.value;
  return {
    Origin: webOrigin,
    ...(csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {}),
  };
}

/** Call the real API through the web origin (same session cookies as the page). */
export async function apiCall<T = unknown>(
  page: Page,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  route: string,
  body?: unknown,
): Promise<{ status: number; body: T }> {
  const response = await page.request.fetch(`${webOrigin}/api/v1${route}`, {
    method,
    headers: await csrfHeaders(page),
    data: body,
  });
  const text = await response.text();
  return {
    status: response.status(),
    body: (text ? JSON.parse(text) : undefined) as T,
  };
}

function siweMessage(input: {
  domain: string;
  scheme: string;
  chainId: number;
  nonce: string;
  expiresAt: string;
}) {
  return [
    `${input.scheme}://${input.domain} wants you to sign in with your Ethereum account:`,
    ownerAccount.address,
    '',
    'Link this wallet to TreasuryPilot',
    '',
    `URI: ${input.scheme}://${input.domain}`,
    'Version: 1',
    `Chain ID: ${input.chainId}`,
    `Nonce: ${input.nonce}`,
    `Issued At: ${new Date().toISOString()}`,
    `Expiration Time: ${input.expiresAt}`,
  ].join('\n');
}

/**
 * Link the Owner dev key to the signed-in account. The web wallet page sends a SIWE statement
 * and chain id the API rejects (see the PR notes), so this goes straight to the API.
 */
export async function linkOwnerWallet(page: Page) {
  const me = await apiCall<{ wallets: Array<{ address: string }> }>(page, 'GET', '/me');
  if (me.body.wallets.some((w) => w.address.toLowerCase() === ownerAccount.address.toLowerCase())) return;
  const nonce = await apiCall<{
    nonce: string;
    domain: string;
    scheme: string;
    chainId: number;
    expiresAt: string;
  }>(page, 'GET', '/auth/siwe/nonce');
  expect(nonce.status).toBe(200);
  const message = siweMessage(nonce.body);
  const signature = await ownerAccount.signMessage({ message });
  const linked = await apiCall(page, 'POST', '/me/wallets', {
    message,
    signature,
  });
  expect([201, 409], JSON.stringify(linked.body) + message).toContain(linked.status);
}

interface MfaState {
  recoveryCodes: string[];
}
const mfaFile = path.join(stateDir, 'mfa.json');

/**
 * Satisfy the API's 10-minute second-factor step-up for the signed-in Owner. The web app has no
 * step-up UI, so this enrols a TOTP factor once (keeping its single-use recovery codes) and then
 * spends one recovery code per login.
 */
export async function stepUp(page: Page) {
  let mfa: MfaState | undefined = existsSync(mfaFile)
    ? (JSON.parse(readFileSync(mfaFile, 'utf8')) as MfaState)
    : undefined;
  if (!mfa) {
    const started = await apiCall<{ factorId: string; otpauthUri: string }>(
      page,
      'POST',
      '/me/mfa/totp',
      { label: 'E2E' },
    );
    expect(started.status).toBe(201);
    const secret = new URL(started.body.otpauthUri).searchParams.get('secret')!;
    const confirmed = await apiCall<{ recoveryCodes: string[] }>(
      page,
      'POST',
      `/me/mfa/totp/${started.body.factorId}/confirm`,
      { code: totp(secret) },
    );
    expect(confirmed.status).toBe(200);
    mfa = { recoveryCodes: confirmed.body.recoveryCodes };
  }
  const recoveryCode = mfa.recoveryCodes.shift();
  if (!recoveryCode)
    throw new Error('Out of recovery codes: reset the E2E database.');
  writeFileSync(mfaFile, JSON.stringify(mfa));
  const done = await apiCall(page, 'POST', '/me/mfa/step-up', { recoveryCode });
  expect(done.status).toBeLessThan(300);
}

function base32Decode(input: string): Buffer {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of input.replace(/=+$/, '').toUpperCase())
    bits += alphabet.indexOf(char).toString(2).padStart(5, '0');
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8)
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

function totp(secret: string): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const digest = createHmac('sha1', base32Decode(secret)).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const value = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, '0');
}

/** Owner session ready for governance work: signed in, wallet linked, step-up fresh. */
export async function ownerSession(page: Page) {
  await loginAs(page, users.owner);
  await linkOwnerWallet(page);
  await stepUp(page);
}

/** Connect the injected dev-key wallet through the app's own connect dialog. */
export async function connectWallet(page: Page) {
  await page
    .getByRole('button', { name: 'Connect wallet to continue' })
    .first()
    .click();
  await page.getByRole('button', { name: 'Browser wallet' }).click();
}
