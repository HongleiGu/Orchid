import { AuthError, NetworkError } from "@orchid/client-core";
import { useState, type FormEvent } from "react";

import { errorMessage } from "../hooks";
import { useSession } from "../session";

export function Connect() {
  const { connect, expiredReason } = useSession();
  // Served same-origin under /console/, the API is at this origin by default.
  const [baseUrl, setBaseUrl] = useState(window.location.origin);
  const [apiKey, setApiKey] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await connect({ baseUrl: baseUrl.trim(), apiKey: apiKey.trim() }, remember);
    } catch (err) {
      if (err instanceof AuthError) setError("The server rejected that key.");
      else if (err instanceof NetworkError) setError(`Could not reach the server. ${errorMessage(err)}`);
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const keyLooksStatic = apiKey.trim() !== "" && !apiKey.trim().startsWith("orc_");

  return (
    <main className="connect">
      <img src="/console/icon.svg" alt="" className="connect-logo" />
      <h1>Orchid Console</h1>
      {expiredReason && <div className="note note-warn">{expiredReason}</div>}

      <form onSubmit={submit} className="stack">
        <label className="field">
          <span>Server</span>
          <input
            type="url" inputMode="url" autoComplete="url" required
            value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
          />
        </label>

        <label className="field">
          <span>API key</span>
          <input
            type="password" autoComplete="current-password" required placeholder="orc_…"
            value={apiKey} onChange={(e) => setApiKey(e.target.value)}
          />
        </label>

        {keyLooksStatic && (
          <div className="note note-warn">
            That looks like the static operator key. It works, but carries no identity — plans and
            attestations won't apply, and it can't be revoked on its own. Prefer a key from
            <code> scripts/seed_test_user.py</code>.
          </div>
        )}

        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>Remember on this device</span>
        </label>

        {error && <div className="note note-error">{error}</div>}

        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </form>
    </main>
  );
}
