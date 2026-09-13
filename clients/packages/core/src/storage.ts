/**
 * Where a client keeps its connection details.
 *
 * An interface because the right answer differs by shell, and the security
 * difference is real:
 *
 *   web (this file)   localStorage / sessionStorage. Readable by any script on
 *                     the origin, so an XSS bug is a stolen key. Acceptable for a
 *                     personal controller served same-origin under a strict CSP,
 *                     with a revocable per-user key — not for a product.
 *   Tauri (later)     the OS keychain via a plugin; the key never touches JS
 *                     storage at all.
 *
 * Keys stored here should always be issued per-user keys, which can be revoked
 * individually, never the static AUTH_API_KEYS operator key.
 */
export interface Credentials {
  baseUrl: string;
  apiKey: string;
  /** Free-form label, e.g. "beijing". */
  label?: string;
}

export interface CredentialStore {
  load(): Promise<Credentials | null>;
  save(credentials: Credentials, options?: { remember?: boolean }): Promise<void>;
  clear(): Promise<void>;
}

const KEY = "orchid.credentials.v1";

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    // Storage can throw outright: private browsing, blocked site data, quota.
    return fallback;
  }
}

/**
 * `remember: true` keeps credentials across restarts (localStorage);
 * otherwise they last only for the tab (sessionStorage) — the sensible
 * choice on a device you do not own.
 */
export class WebCredentialStore implements CredentialStore {
  async load(): Promise<Credentials | null> {
    const raw = safe(() => sessionStorage.getItem(KEY) ?? localStorage.getItem(KEY), null);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as Credentials;
      return parsed.baseUrl && parsed.apiKey ? parsed : null;
    } catch {
      return null;
    }
  }

  async save(credentials: Credentials, options: { remember?: boolean } = {}): Promise<void> {
    const raw = JSON.stringify(credentials);
    safe(() => {
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
      (options.remember ? localStorage : sessionStorage).setItem(KEY, raw);
    }, undefined);
  }

  async clear(): Promise<void> {
    safe(() => {
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
    }, undefined);
  }
}

/** For tests and for shells that manage secrets elsewhere. */
export class MemoryCredentialStore implements CredentialStore {
  private value: Credentials | null = null;
  async load() { return this.value; }
  async save(credentials: Credentials) { this.value = credentials; }
  async clear() { this.value = null; }
}
