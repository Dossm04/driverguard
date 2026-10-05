import { test, expect } from "@playwright/test";
import { IDBFactory } from "fake-indexeddb";
import { cameraOwner, saveCameraEvents, listCameraEvents, flushCameraEvents, type CameraEventBody } from "../../lib/camera-queue";

test.describe.configure({ mode: "serial" });
const originalFetch = globalThis.fetch;
const tokens = new Map<string, string>();
function login(id: number) {
  tokens.set("dg-token-driver", `header.${Buffer.from(JSON.stringify({ sub: String(id), role: "driver" })).toString("base64url")}.sig`);
  tokens.set("dg-refresh-driver", `refresh-${id}`);
}
const body = (uuid = "event-1"): CameraEventBody => ({ uuid, type: "microsleep", severity: "critical", confidence: 0.9,
  ts: "2026-10-05T01:00:00Z", lat: null, lon: null, gps_valid: false, speed_kmh: null, value: 2, note: "test" });
const ok = (n = 1, duplicates = 0) => new Response(JSON.stringify({ accepted: n, duplicates }));
test.beforeEach(() => {
  tokens.clear();
  Object.assign(globalThis, {
    indexedDB: new IDBFactory(),
    window: { location: { pathname: "/driver/camera", href: "/driver/camera" } },
    localStorage: { getItem: (key: string) => tokens.get(key) ?? null, setItem: (key: string, value: string) => tokens.set(key, value), removeItem: (key: string) => tokens.delete(key) },
  });
  login(1);
});
test.afterEach(async () => { globalThis.fetch = originalFetch; await new Promise((r) => setTimeout(r, 5)); });

for (const status of [401, 403, 408, 429, 500, 503]) test(`camera events survive HTTP ${status} and retry`, async () => {
  const owner = cameraOwner()!;
  await saveCameraEvents(owner, [body()]);
  globalThis.fetch = async () => new Response("{}", { status });
  await flushCameraEvents();
  expect(await listCameraEvents(owner)).toHaveLength(1);
  login(1);
  globalThis.fetch = async () => ok();
  await flushCameraEvents();
  expect(await listCameraEvents(owner)).toHaveLength(0);
});

test("network failure preserves UUID; a duplicate acknowledgement clears it", async () => {
  await saveCameraEvents(cameraOwner()!, [body()]);
  globalThis.fetch = async () => { throw new TypeError("offline"); };
  await flushCameraEvents();
  expect((await listCameraEvents())[0].body.uuid).toBe("event-1");
  globalThis.fetch = async () => ok(0, 1);
  await flushCameraEvents();
  expect(await listCameraEvents()).toHaveLength(0);
});

test("another driver never receives the original driver's queued data", async () => {
  const owner = cameraOwner()!;
  await saveCameraEvents(owner, [body()]);
  login(2);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return ok(); };
  await flushCameraEvents();
  expect(calls).toBe(0);
  expect(await listCameraEvents()).toHaveLength(0);
  expect(await listCameraEvents(owner)).toHaveLength(1);
  login(1);
  await flushCameraEvents();
  expect(await listCameraEvents(owner)).toHaveLength(0);
});

test("account change during a 401 request cannot replay an event as the next driver", async () => {
  const owner = cameraOwner()!;
  await saveCameraEvents(owner, [body()]);
  let calls = 0;
  globalThis.fetch = async () => { calls++; login(2); return new Response("{}", { status: 401 }); };
  await flushCameraEvents();
  expect(calls).toBe(1);
  expect(await listCameraEvents(owner)).toHaveLength(1);
  expect(cameraOwner()).not.toBe(owner);
});

test("account change during token refresh does not overwrite the new login", async () => {
  const owner = cameraOwner()!;
  await saveCameraEvents(owner, [body()]);
  globalThis.fetch = async (url) => {
    if (String(url).endsWith("/auth/refresh")) { login(2); return new Response(JSON.stringify({ access_token: "old-driver-token" })); }
    return new Response("{}", { status: 401 });
  };
  await flushCameraEvents();
  expect(cameraOwner()).toContain("|2");
  expect(await listCameraEvents(owner)).toHaveLength(1);
});

test("invalid row is kept for export and does not discard or block valid rows", async () => {
  await saveCameraEvents(cameraOwner()!, [body("bad"), body("good")]);
  globalThis.fetch = async (_url, options) => {
    const batch = JSON.parse(String(options?.body)) as CameraEventBody[];
    return batch.some((b) => b.uuid === "bad") ? new Response(JSON.stringify({ detail: "invalid test row" }), { status: 422 }) : ok(batch.length);
  };
  await flushCameraEvents();
  const left = await listCameraEvents();
  expect(left).toHaveLength(1);
  expect(left[0].body.uuid).toBe("bad");
  expect(left[0].rejected).toContain("invalid test row");
});

test("concurrent flushes send one batch, and incomplete acknowledgements keep data", async () => {
  await saveCameraEvents(cameraOwner()!, [body()]);
  let calls = 0;
  globalThis.fetch = async () => { calls++; await new Promise((r) => setTimeout(r, 10)); return ok(0); };
  await Promise.all([flushCameraEvents(), flushCameraEvents()]);
  expect(calls).toBe(1);
  expect(await listCameraEvents()).toHaveLength(1);
});

test("more than one batch is delivered with stable UUIDs", async () => {
  await saveCameraEvents(cameraOwner()!, Array.from({ length: 43 }, (_, i) => body(`event-${i}`)));
  const sizes: number[] = [];
  globalThis.fetch = async (_url, options) => { const n = JSON.parse(String(options?.body)).length; sizes.push(n); return ok(n); };
  await flushCameraEvents();
  expect(sizes).toEqual([20, 20, 3]);
  expect(await listCameraEvents()).toHaveLength(0);
});
