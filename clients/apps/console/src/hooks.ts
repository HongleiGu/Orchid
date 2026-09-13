import { useCallback, useEffect, useRef, useState } from "react";

import { isAuthError, useSession } from "./session";

/** Hash routing: "#/runs/01ABC" -> ["runs", "01ABC"]. Hash, not history, so the
 * same build works under /console/, from a file:// or tauri:// origin, and
 * needs no server-side fallback. */
export function useRoute(): [string[], (path: string) => void] {
  const parse = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [segments, setSegments] = useState<string[]>(parse);
  useEffect(() => {
    const onChange = () => setSegments(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback((path: string) => {
    window.location.hash = `#/${path.replace(/^\/+/, "")}`;
  }, []);
  return [segments, navigate];
}

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/**
 * Run an async loader, re-running when `deps` change or `reload()` is called.
 * An AuthError anywhere ends the session, so an expired key surfaces once as
 * "connect again" rather than as a red error on every screen.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], options: { pollMs?: number } = {}): AsyncState<T> {
  const { expire } = useSession();
  const [state, setState] = useState<{ data: T | undefined; error: unknown; loading: boolean }>({
    data: undefined, error: undefined, loading: true,
  });
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    loaderRef.current().then(
      (data) => { if (!cancelled) setState({ data, error: undefined, loading: false }); },
      (error) => {
        if (cancelled) return;
        if (isAuthError(error)) expire();
        setState((s) => ({ data: s.data, error, loading: false }));
      },
    );
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!options.pollMs) return;
    const id = setInterval(() => {
      // Skip polling while the app is in the background: it costs battery and
      // requests for a screen nobody is looking at.
      if (document.visibilityState === "visible") setTick((t) => t + 1);
    }, options.pollMs);
    return () => clearInterval(id);
  }, [options.pollMs]);

  return { ...state, reload: () => setTick((t) => t + 1) };
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
