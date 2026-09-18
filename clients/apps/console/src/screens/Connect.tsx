import { AuthError, NetworkError } from "@orchid/client-core";
import { useState, type FormEvent } from "react";

import { RedeemDevice } from "../AddDevice";
import { errorMessage } from "../hooks";
import { useSession } from "../session";

/** A code prefilled from a #/pair/<code> deep link goes straight to the pairing tab. */
export function Connect({ presetCode }: { presetCode?: string }) {
  const { connect, expiredReason } = useSession();
  const [mode, setMode] = useState<"key" | "pair">(presetCode ? "pair" : "key");
  const [baseUrl, setBaseUrl] = useState(window.location.origin);

  async function establish(apiKey: string, remember: boolean) {
    await connect({ baseUrl: baseUrl.trim(), apiKey }, remember);
  }

  return (
    <main className="connect">
      <img src="/console/icon.svg" alt="" className="connect-logo" />
      <h1>Orchid Console</h1>
      {expiredReason && <div className="note note-warn">{expiredReason}</div>}

      <div className="field">
        <span>Server</span>
        <input type="url" inputMode="url" autoComplete="url" value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)} />
      </div>

      <div className="chips" role="tablist">
        <button role="tab" aria-selected={mode === "key"} className={`chip ${mode === "key" ? "chip-on" : ""}`}
          onClick={() => setMode("key")}>API key</button>
        <button role="tab" aria-selected={mode === "pair"} className={`chip ${mode === "pair" ? "chip-on" : ""}`}
          onClick={() => setMode("pair")}>Pair with a code</button>
      </div>

      {mode === "key"
        ? <KeyForm onConnect={establish} />
        : <RedeemDevice baseUrl={baseUrl} presetCode={presetCode}
            onPaired={(apiKey) => establish(apiKey, true)} onCancel={() => setMode("key")} />}
    </main>
  );
}

function KeyForm({ onConnect }: { onConnect: (apiKey: string, remember: boolean) => Promise<void> }) {
  const [apiKey, setApiKey] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConnect(apiKey.trim(), remember);
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
    <form onSubmit={submit} className="stack">
      <label className="field">
        <span>API key</span>
        <input type="password" autoComplete="current-password" required placeholder="orc_…"
          value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
      </label>

      {keyLooksStatic && (
        <div className="note note-warn">
          That looks like the static operator key. It works, but carries no identity — plans and
          attestations won't apply, and it can't pair devices. Prefer a key issued to a user.
        </div>
      )}

      <label className="check">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <span>Remember on this device</span>
      </label>

      {error && <div className="note note-error">{error}</div>}
      <button className="primary" type="submit" disabled={busy}>{busy ? "Connecting…" : "Connect"}</button>
    </form>
  );
}
