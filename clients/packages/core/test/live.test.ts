/**
 * Against a real deployment. Skipped unless pointed at one:
 *
 *   ORCHID_LIVE_URL=https://www.dotslash.cn \
 *   ORCHID_LIVE_KEY=orc_... \
 *   ORCHID_LIVE_RUN=<id of a finished run> \
 *   pnpm --filter @orchid/client-core test
 *
 * The unit tests prove the parser against assumptions about the wire format;
 * this proves it against what the server and its proxy actually send — which
 * is where both SSE bugs so far (duplicated events, a stream that never
 * closed) were found.
 */
import { describe, expect, it } from "vitest";

import { OrchidClient } from "../src/client";
import type { RunEvent } from "../src/types";

const url = process.env.ORCHID_LIVE_URL;
const key = process.env.ORCHID_LIVE_KEY;
const runId = process.env.ORCHID_LIVE_RUN;

describe.skipIf(!url || !key)("live deployment", () => {
  const client = () => new OrchidClient({ baseUrl: url!, apiKey: key! });

  it("is healthy and accepts the key", async () => {
    expect((await client().health()).status).toBe("ok");
    await client().verifyKey();
  });

  it.skipIf(!runId)("streams a finished run to its end, then closes", async () => {
    const detail = await client().getRun(runId!);
    const seen: RunEvent[] = [];
    const handle = client().streamRun(runId!, { onEvent: (e) => seen.push(e) });

    const outcome = await Promise.race([
      handle.done,
      new Promise((resolve) => setTimeout(() => resolve("timeout"), 30_000)),
    ]);
    handle.close();

    // "timeout" here is the old server bug: stream never closes after the end.
    expect(outcome).toBe("ended");
    const seqs = seen.map((e) => e.seq);
    expect(new Set(seqs).size, "no event delivered twice").toBe(seqs.length);
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
    expect(seen.at(-1)?.type).toBe("terminated");
    expect(seen.length).toBe(detail.events.length);
  }, 40_000);

  it.skipIf(!runId)("resumes from a Last-Event-ID cursor", async () => {
    const all: RunEvent[] = [];
    await client().streamRun(runId!, { onEvent: (e) => all.push(e) }).done;
    const cursor = all[Math.floor(all.length / 2)]!.seq;

    const rest: RunEvent[] = [];
    await client().streamRun(runId!, { lastEventId: cursor, onEvent: (e) => rest.push(e) }).done;

    expect(rest.length).toBeGreaterThan(0);
    expect(rest.every((e) => e.seq > cursor)).toBe(true);
    expect(rest.map((e) => e.seq)).toEqual(all.filter((e) => e.seq > cursor).map((e) => e.seq));
  }, 40_000);
});
