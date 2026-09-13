# Orchid clients

Everything that talks to an Orchid deployment from outside it.

```
clients/
  packages/core/     @orchid/client-core — typed API client, authenticated SSE,
                     credential storage interface. No framework, no DOM beyond fetch.
  apps/console/      Orchid Console — mobile-first PWA for controlling a deployment.
  nginx/             how the console container serves itself (CSP, caching).
  Dockerfile         builds the console, running the core's tests as a gate.
```

The split is the point. The console is a personal operator tool, but the core is
written to be reused as-is by a desktop/mobile shell and by the publisher app —
they would supply their own UI, their own `fetch`, and their own credential store.

## Using the console

Deployed with the stack at **`https://<domain>/console/`** (the `console` service
in `docker-compose.yml`, routed by the gateway nginx).

1. Issue yourself a per-user key on the server:
   `docker compose exec backend python scripts/seed_test_user.py --identifier me --plan standard`
2. Open `/console/`, paste the key, connect.
3. Install it: **iPhone** Safari → 分享 → 添加到主屏幕 · **Android** browser menu →
   安装应用 · **desktop** Chrome/Edge → the install icon in the address bar.

It covers: server health and 30-day spend; templates, including reading and
accepting a required attestation before a run; runs with live progress over SSE,
cancellation, the result, and which step the cost went to.

Use an **issued** key, not the static `AUTH_API_KEYS` one. The static key works but
carries no identity, so plans and attestations don't apply to it, and it can't be
revoked without rotating it for everyone.

## Developing

```bash
cd clients
pnpm install
pnpm dev:console                          # Vite on :5173, proxies /api to 127.0.0.1:8000
ORCHID_DEV_API=https://www.dotslash.cn pnpm dev:console   # …or to a remote server
pnpm test                                 # core unit tests
pnpm typecheck
```

Against a real deployment — this is the test that catches what unit tests can't,
because it exercises the server and its proxy rather than assumptions about them:

```bash
ORCHID_LIVE_URL=https://www.dotslash.cn ORCHID_LIVE_KEY=orc_... ORCHID_LIVE_RUN=<finished run id> \
  pnpm --filter @orchid/client-core test
```

### Adding a tool to the console

Add one entry to `apps/console/src/modules.ts`. A module gets a route
(`#/<id>/...`), a tab if `nav: true`, and a line on the settings page; its
component receives the path segments after its id.

## Design decisions worth knowing

**SSE over `fetch`, not `EventSource`.** `EventSource` cannot send headers, and the
backend authenticates only through headers — it refuses tokens in query strings so
they never reach access logs. So `core/src/sse.ts` reads the response body as a
stream: it parses SSE incrementally, resumes with `Last-Event-ID` across dropped
connections, de-duplicates by sequence number, reconnects silent connections after
70s (the server sends a keepalive every 25s), gives up immediately on 401/403/404,
and stops at the run-level `terminated` event but not at a CollabGroup's.

**The key lives in web storage, and that is only acceptable because of the CSP.**
localStorage is readable by any script on the origin, so an XSS bug would be a
stolen key. The console is served same-origin with the API under
`connect-src 'self'` and no inline scripts, so injected script could not send the
key anywhere else. Consequence: *the hosted console can only talk to the server that
served it.* "Remember on this device" off uses sessionStorage instead.

**Verbosity is requested high and capped by the server.** The console asks for
`debug`; a full deployment returns agent output and routing, the run-only edition
caps it at `info` and says so in the response. The client never decides what it is
allowed to see.

**Hash routing**, so the same build works under `/console/`, from `tauri://`, or
from a file, with no server-side fallback rules.

**API responses are never cached** by the service worker — only the app shell. A
stale run status or attestation shown as current would be wrong invisibly.

## Reuse path

**Desktop and mobile apps (Tauri 2).** Tauri 2 targets Windows/macOS/Linux and
iOS/Android from one project, and can load this console build unchanged. What
changes:

- Swap `WebCredentialStore` for a keychain-backed `CredentialStore` — the interface
  exists for this; the key then never touches JS storage.
- The app is no longer same-origin, so add its origin to `APP_CORS_ORIGINS` on the
  server (`tauri://localhost` on macOS/iOS, `http://tauri.localhost` on
  Windows/Android).
- The CSP above belongs to the web deployment; a Tauri build needs its own.

**The publisher app** imports `@orchid/client-core` for auth, runs and streaming,
and brings its own UI.

**React Native** would need a different stream transport: its `fetch` has no
streaming body. `openRunStream`'s contract is what to reimplement.

## Limits in mainland China

- **Push notifications.** Web Push on Android goes through Firebase Cloud
  Messaging, which is blocked in the mainland, so a PWA can't notify Android users
  there. iOS 16.4+ home-screen apps use APNs, which works. For "run finished"
  alerts to reach everyone, use another channel — a WeChat 服务号 template
  message, SMS, or polling while the app is open (what the console does now).
- **App stores.** Distributing a native app in the mainland needs **APP备案**, and
  most Android stores additionally ask for a 软件著作权 certificate; Apple's China
  storefront also checks the filing. A PWA served from the already-filed domain
  sidesteps store distribution entirely, which is much of why this starts as one.
  Check current requirements before shipping a store build — they have tightened
  repeatedly.
