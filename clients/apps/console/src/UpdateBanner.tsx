import { useRegisterSW } from "virtual:pwa-register/react";

/**
 * The service worker caches the app shell, so a deployed update would otherwise
 * stay invisible until every tab closed. Ask instead of reloading underneath
 * someone who may be mid-way through reading an attestation.
 */
export function UpdateBanner() {
  const { needRefresh: [needRefresh, setNeedRefresh], updateServiceWorker } = useRegisterSW();
  if (!needRefresh) return null;
  return (
    <div className="update" role="status">
      <span>A new version is available.</span>
      <button className="link" onClick={() => updateServiceWorker(true)}>Reload</button>
      <button className="link" onClick={() => setNeedRefresh(false)}>Later</button>
    </div>
  );
}
