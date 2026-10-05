import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash, webcrypto } from "node:crypto";
import vm from "node:vm";

function worker() {
  type Cache = Map<string, Response>;
  const stores = new Map<string, Cache>();
  const listeners: Record<string, (event: unknown) => void> = {};
  const key = (value: string | Request) => new URL(typeof value === "string" ? value : value.url, "https://driver.test").pathname;
  const caches = {
    async open(name: string) {
      if (!stores.has(name)) stores.set(name, new Map());
      const rows = stores.get(name)!;
      return { match: async (url: string | Request) => rows.get(key(url))?.clone(), put: async (url: string | Request, r: Response) => { rows.set(key(url), r.clone()); } };
    },
    keys: async () => [...stores.keys()], delete: async (name: string) => stores.delete(name),
  };
  const files = new Map<string, string>();
  for (const name of ["face_landmarker.task", "hand_landmarker.task", "third.task", "fourth.task", "fifth.task"]) files.set(`/models/${name}`, `bytes-for-${name}`);
  const manifest = { version: "test-build", missing: [] as string[], assets: [...files].map(([url, bytes]) => ({url, bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex")})) };
  let broken = "";
  const sandbox = { caches, URL, Response, AbortSignal, crypto: webcrypto, Date,
    self: { location: { origin: "https://driver.test" }, addEventListener: (name: string, handler: (event: unknown) => void) => {listeners[name] = handler;} },
    fetch: async (input: string | Request) => {
      const url = key(input);
      if (url === broken) throw new Error("connection dropped");
      if (url === "/offline-assets.json") return Response.json(manifest);
      if (url === "/models/browser-model.json") return new Response("", {status:404});
      if (files.has(url)) return new Response(files.get(url));
      return new Response("<!doctype html><html></html>", {headers:{"Content-Type":"text/html"}});
    },
  };
  vm.runInNewContext(readFileSync(resolve("public/sw.js"), "utf8"), sandbox);
  async function message(type: string) {
    const messages: { done?: { ready: boolean }; error?: string }[] = [];
    let job: Promise<void> = Promise.resolve();
    listeners.message({data:{type},ports:[{postMessage:(m: typeof messages[number])=>messages.push(m)}],waitUntil:(p:Promise<void>)=>{job=p;}});
    await job; return messages.at(-1)!;
  }
  return { stores, files, manifest, listeners, message, breakAt: (path: string) => {broken=path;} };
}

test("preparation verifies files and marks a complete bundle ready", async () => {
  const w=worker();
  expect((await w.message("DG_OFFLINE_PREPARE")).done?.ready).toBe(true);
  expect((await w.message("DG_OFFLINE_STATUS")).done?.ready).toBe(true);
});
test("bad checksum cannot be marked ready", async () => {
  const w=worker();w.files.set("/models/face_landmarker.task","corrupted");
  expect((await w.message("DG_OFFLINE_PREPARE")).error).toBeTruthy();
  expect((await w.message("DG_OFFLINE_STATUS")).done?.ready).toBe(false);
});
test("incomplete server installation cannot be marked ready", async () => {
  const w=worker();w.manifest.missing.push("hand_landmarker.task");
  expect((await w.message("DG_OFFLINE_PREPARE")).error).toContain("модели");
});
test("failed update preserves previous complete bundle", async () => {
  const w=worker();await w.message("DG_OFFLINE_PREPARE");
  w.breakAt("/models/hand_landmarker.task");
  expect((await w.message("DG_OFFLINE_PREPARE")).error).toBeTruthy();
  expect((await w.message("DG_OFFLINE_STATUS")).done?.ready).toBe(true);
});
test("evicted model revokes readiness", async () => {
  const w=worker();await w.message("DG_OFFLINE_PREPARE");
  for (const rows of w.stores.values()) rows.delete("/models/face_landmarker.task");
  expect((await w.message("DG_OFFLINE_STATUS")).done?.ready).toBe(false);
});
test("API, login POST and external URLs are never cached", () => {
  const w=worker();let intercepted=0;
  for (const request of [new Request("https://driver.test/api/v1/drivers/me"),new Request("https://driver.test/driver/login",{method:"POST"}),new Request("https://other.test/models/private")]) {
    w.listeners.fetch({request,respondWith:()=>{intercepted++;}});
  }
  expect(intercepted).toBe(0);
});
