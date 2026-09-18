import { describe, expect, it } from "vitest";

import { OrchidClient } from "../src/client";
import { AuthError, ForbiddenError, NetworkError, NotFoundError } from "../src/errors";
import { MemoryCredentialStore } from "../src/storage";

function fakeFetch(respond: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: { url: string; init: RequestInit }[] = [];
  const impl = (async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return respond(url, init);
  }) as unknown as typeof fetch;
  return { impl, calls };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("OrchidClient", () => {
  it("sends the key as a bearer header, and normalises the base URL", async () => {
    const { impl, calls } = fakeFetch(() => json(200, { data: [] }));
    const client = new OrchidClient({ baseUrl: "https://x.cn///", apiKey: "orc_abc", fetchImpl: impl });
    await client.listTemplates();
    expect(calls[0]!.url).toBe("https://x.cn/api/v1/templates");
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe("Bearer orc_abc");
  });

  it("does not send the key to the public health endpoint", async () => {
    const { impl, calls } = fakeFetch(() => json(200, { status: "ok" }));
    await new OrchidClient({ baseUrl: "https://x", apiKey: "orc_abc", fetchImpl: impl }).health();
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("maps 401 to AuthError and 403 to ForbiddenError, keeping the server's reason", async () => {
    const client = (status: number, message: string) => new OrchidClient({
      baseUrl: "https://x", apiKey: "k",
      fetchImpl: fakeFetch(() => json(status, { error: { message, code: null } })).impl,
    });

    await expect(client(401, "Missing or invalid API key").verifyKey()).rejects.toBeInstanceOf(AuthError);

    const forbidden = client(403, "Template 'x' is not included in your plan (trial)").runTemplate("x");
    await expect(forbidden).rejects.toBeInstanceOf(ForbiddenError);
    await expect(forbidden).rejects.toThrow("not included in your plan");

    await expect(client(404, "Run not found").getRun("r")).rejects.toBeInstanceOf(NotFoundError);
  });

  it("explains a proxy error page instead of reporting an unparseable body", async () => {
    const { impl } = fakeFetch(() => new Response("<html>502 Bad Gateway</html>", { status: 502 }));
    const run = new OrchidClient({ baseUrl: "https://x", apiKey: "k", fetchImpl: impl }).listRuns();
    await expect(run).rejects.toThrow(/gateway could not reach the backend/);
  });

  it("reports an unreachable server as a NetworkError", async () => {
    const { impl } = fakeFetch(() => { throw new TypeError("fetch failed"); });
    await expect(new OrchidClient({ baseUrl: "https://down", apiKey: "k", fetchImpl: impl }).health())
      .rejects.toBeInstanceOf(NetworkError);
  });

  it("builds run queries and posts attestation versions", async () => {
    const { impl, calls } = fakeFetch(() => json(200, { data: {}, meta: { page: 1, page_size: 20, total: 0 } }));
    const client = new OrchidClient({ baseUrl: "https://x", apiKey: "k", fetchImpl: impl });

    await client.listRuns({ page: 2, status: "running" });
    expect(calls[0]!.url).toBe("https://x/api/v1/runs?page=2&status=running");

    await client.acceptAttestation("securities_advisory", "1");
    expect(calls[1]!.init.method).toBe("POST");
    expect(JSON.parse(calls[1]!.init.body as string)).toEqual({ version: "1" });
  });
});

describe("MemoryCredentialStore", () => {
  it("round-trips and clears", async () => {
    const store = new MemoryCredentialStore();
    await store.save({ baseUrl: "https://x", apiKey: "k" });
    expect(await store.load()).toEqual({ baseUrl: "https://x", apiKey: "k" });
    await store.clear();
    expect(await store.load()).toBeNull();
  });
});

// ── vault + pairing (OR-46/47) ───────────────────────────────────────────────

describe("OrchidClient vault and pairing", () => {
  it("downloads a file with the bearer header and reads the returned name/type", async () => {
    const { impl, calls } = fakeFetch(() =>
      new Response(new Blob([new Uint8Array([1, 2, 3])]), {
        status: 200,
        headers: { "Content-Type": "application/pdf" },
      }),
    );
    const client = new OrchidClient({ baseUrl: "https://x", apiKey: "orc_k", fetchImpl: impl });
    const file = await client.downloadVaultFile("市场", "报告.pdf");

    expect(calls[0]!.url).toBe("https://x/api/v1/vault/projects/%E5%B8%82%E5%9C%BA/%E6%8A%A5%E5%91%8A.pdf/download");
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe("Bearer orc_k");
    expect(file.mediaType).toBe("application/pdf");
    expect(file.blob.size).toBe(3);
  });

  it("redeems a pairing code without a key, and surfaces the server's refusal", async () => {
    const ok = fakeFetch(() => json(200, { data: { api_key: "orc_new", key_id: "01K", identifier: "alice" } }));
    const redeemed = await OrchidClient.redeemPairing("https://x/", "abcde-fghjk", "phone", ok.impl);
    expect(redeemed.api_key).toBe("orc_new");
    expect(ok.calls[0]!.url).toBe("https://x/api/v1/pairing/redeem");
    expect((ok.calls[0]!.init.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(JSON.parse(ok.calls[0]!.init.body as string)).toEqual({ code: "abcde-fghjk", device_name: "phone" });

    const bad = fakeFetch(() => json(400, { error: { message: "That code is invalid or has expired." } }));
    await expect(OrchidClient.redeemPairing("https://x", "zzzzz-zzzzz", "phone", bad.impl))
      .rejects.toThrow("invalid or has expired");
  });

  it("polls pairing status", async () => {
    const { impl, calls } = fakeFetch(() => json(200, { data: { id: "01K", status: "redeemed", expires_at: "", redeemed_at: null, device_name: "phone" } }));
    const status = await new OrchidClient({ baseUrl: "https://x", apiKey: "k", fetchImpl: impl }).pairingStatus("01K");
    expect(status.status).toBe("redeemed");
    expect(calls[0]!.url).toBe("https://x/api/v1/pairing/01K");
  });
});
