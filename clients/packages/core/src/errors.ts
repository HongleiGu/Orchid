/**
 * Errors a client can act on differently. The distinction that matters most in
 * practice is 401 versus 403: 401 means the key is wrong or revoked (re-enter
 * it), 403 means the key is fine but this edition, plan or attestation does not
 * allow the action (explain it — asking for the key again would be useless).
 */
export class OrchidError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = new.target.name;
  }
}

/** Missing, wrong, or revoked key. */
export class AuthError extends OrchidError {}

/** Authenticated, but not permitted: run-only edition, plan, or attestation. */
export class ForbiddenError extends OrchidError {}

export class NotFoundError extends OrchidError {}

/** The request never produced an HTTP response: offline, DNS, TLS, proxy. */
export class NetworkError extends OrchidError {
  constructor(message: string, override readonly cause?: unknown) {
    super(message, 0);
  }
}

export function errorForStatus(status: number, message: string, code: string | null): OrchidError {
  if (status === 401) return new AuthError(message, status, code);
  if (status === 403) return new ForbiddenError(message, status, code);
  if (status === 404) return new NotFoundError(message, status, code);
  return new OrchidError(message, status, code);
}
