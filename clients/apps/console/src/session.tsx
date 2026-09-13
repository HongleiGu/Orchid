import {
  AuthError,
  OrchidClient,
  WebCredentialStore,
  type Credentials,
} from "@orchid/client-core";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

interface Session {
  client: OrchidClient;
  credentials: Credentials;
}

interface SessionContextValue {
  session: Session | null;
  loading: boolean;
  connect: (credentials: Credentials, remember: boolean) => Promise<void>;
  disconnect: () => Promise<void>;
  /** Call when a request fails with AuthError: the stored key is no longer good. */
  expire: () => void;
  expiredReason: string | null;
}

const SessionContext = createContext<SessionContextValue | null>(null);
const store = new WebCredentialStore();

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [expiredReason, setExpiredReason] = useState<string | null>(null);

  useEffect(() => {
    store.load().then((credentials) => {
      if (credentials) setSession({ credentials, client: new OrchidClient(credentials) });
      setLoading(false);
    });
  }, []);

  const connect = useCallback(async (credentials: Credentials, remember: boolean) => {
    const client = new OrchidClient(credentials);
    // Verify before storing, so a typo never gets remembered.
    await client.health();
    await client.verifyKey();
    await store.save(credentials, { remember });
    setExpiredReason(null);
    setSession({ credentials, client });
  }, []);

  const disconnect = useCallback(async () => {
    await store.clear();
    setSession(null);
  }, []);

  const expire = useCallback(() => {
    setExpiredReason("The server rejected the saved key — it may have been revoked. Connect again.");
    setSession(null);
  }, []);

  const value = useMemo(
    () => ({ session, loading, connect, disconnect, expire, expiredReason }),
    [session, loading, connect, disconnect, expire, expiredReason],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}

/** The connected client. Only valid inside the connected shell. */
export function useClient(): OrchidClient {
  const { session } = useSession();
  if (!session) throw new Error("useClient without a session");
  return session.client;
}

export function isAuthError(error: unknown): error is AuthError {
  return error instanceof AuthError;
}
