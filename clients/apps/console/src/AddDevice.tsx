import type { PairingCode } from "@orchid/client-core";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "./hooks";
import { qrDataUrl } from "./qr";
import { useClient, useSession } from "./session";
import { Card, ErrorNote } from "./ui";

/**
 * Pair another device from this signed-in one. Shows a QR and a short code; the
 * new device scans or types it and receives its own key. We poll the code's
 * status so this screen confirms the moment the other device is in.
 *
 * The QR encodes a deep link to the console's own pair page carrying the code,
 * so the camera app opens straight into redemption. The short code is the
 * fallback for when the two devices can't see each other's screens, or for iOS,
 * where scanning with the system camera opens Safari rather than the installed
 * app — there the code must be typed into the app by hand.
 */
export function AddDevice() {
  const client = useClient();
  const { session } = useSession();
  const [pairing, setPairing] = useState<PairingCode | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "creating" | "waiting" | "done" | "expired">("idle");
  const [error, setError] = useState<unknown>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => () => clearInterval(pollRef.current), []);

  async function start() {
    clearInterval(pollRef.current);
    setState("creating");
    setError(null);
    try {
      const code = await client.createPairing();
      setPairing(code);
      const base = session?.credentials.baseUrl ?? window.location.origin;
      const link = `${base.replace(/\/+$/, "")}/console/#/pair/${encodeURIComponent(code.code)}`;
      setQr(await qrDataUrl(link));
      setState("waiting");
      poll(code);
    } catch (err) {
      setError(err);
      setState("idle");
    }
  }

  function poll(code: PairingCode) {
    const deadline = new Date(code.expires_at).getTime();
    pollRef.current = setInterval(async () => {
      if (Date.now() > deadline) {
        clearInterval(pollRef.current);
        setState("expired");
        return;
      }
      try {
        const status = await client.pairingStatus(code.id);
        if (status.status === "redeemed") {
          clearInterval(pollRef.current);
          setState("done");
        } else if (status.status === "expired") {
          clearInterval(pollRef.current);
          setState("expired");
        }
      } catch {
        // A transient poll failure is not worth surfacing; the next tick retries.
      }
    }, 2500);
  }

  return (
    <Card title="Add a device">
      {state === "idle" && (
        <>
          <p className="muted">
            Generate a one-time code, then scan it or type it on the other device to sign it in.
            It gets its own key, so you can revoke that device on its own later.
          </p>
          <button className="primary" onClick={start}>Generate a pairing code</button>
          <ErrorNote error={error} />
        </>
      )}

      {state === "creating" && <p className="muted">Generating…</p>}

      {(state === "waiting" || state === "expired" || state === "done") && pairing && (
        <div className="pair">
          {state === "done" ? (
            <div className="note note-ok">Device paired. It is now signed in with its own key.</div>
          ) : state === "expired" ? (
            <div className="note note-warn">This code expired. Generate a new one.</div>
          ) : (
            <>
              {qr && <img className="qr" src={qr} alt="Pairing QR code" width={240} height={240} />}
              <div className="pair-code" aria-label="pairing code">{pairing.code}</div>
              <p className="list-sub center">
                On the new device: open the console and choose “Pair with a code”, or scan this with its
                camera. Valid for {Math.round(pairing.ttl_seconds / 60)} minutes.
              </p>
            </>
          )}
          <button className="secondary" onClick={start}>
            {state === "waiting" ? "New code" : "Generate another"}
          </button>
        </div>
      )}
    </Card>
  );
}

// ── redemption, for a device that is not signed in yet ────────────────────────

/**
 * Shown on the Connect screen and reachable at #/pair/<code>. Redeems a code and
 * hands the resulting key back so the caller can establish a session with it.
 */
export function RedeemDevice({ baseUrl, presetCode, onPaired, onCancel }: {
  baseUrl: string;
  presetCode?: string;
  onPaired: (apiKey: string) => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState(presetCode ?? "");
  const [deviceName, setDeviceName] = useState(defaultDeviceName());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function redeem() {
    setBusy(true);
    setError(null);
    try {
      const { OrchidClient } = await import("@orchid/client-core");
      const result = await OrchidClient.redeemPairing(baseUrl, code.trim(), deviceName.trim() || "device");
      onPaired(result.api_key);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <p className="muted">
        Enter the code shown on a device that is already signed in
        {" "}(<span className="muted">Settings → Add a device</span>).
      </p>
      <label className="field">
        <span>Pairing code</span>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="ABCDE-FGHJK"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} inputMode="text" />
      </label>
      <label className="field">
        <span>Name this device</span>
        <input value={deviceName} onChange={(e) => setDeviceName(e.target.value)} maxLength={40} />
      </label>
      {error && <div className="note note-error">{error}</div>}
      <button className="primary" onClick={redeem} disabled={busy || code.trim().length < 10}>
        {busy ? "Pairing…" : "Pair this device"}
      </button>
      <button className="link" onClick={onCancel}>Use an API key instead</button>
    </div>
  );
}

function defaultDeviceName(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return "Android phone";
  if (/Mac/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows PC";
  return "device";
}
