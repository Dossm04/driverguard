import { test, expect } from "@playwright/test";
import { IDBFactory } from "fake-indexeddb";
import { savePendingChecklist, countPendingChecklists, flushPendingChecklists } from "../../lib/offline-queue";

test.describe.configure({ mode: "serial" });
const originalFetch = globalThis.fetch;

test.beforeEach(() => {
  Object.assign(globalThis, {
    indexedDB: new IDBFactory(),
    window: { location: { pathname: "/driver/checklist", href: "/driver/checklist" } },
    localStorage: { getItem: () => null, setItem: () => undefined, removeItem: () => undefined },
  });
});
test.afterEach(() => { globalThis.fetch = originalFetch; });

for (const status of [401, 403, 408, 429, 503]) {
  test(`чек-лист с фото сохраняется при временном отказе ${status}`, async () => {
    await savePendingChecklist({ created_at: new Date().toISOString(), answers: {}, photos: [
      { slot: "tires", name: "wheel.jpg", type: "image/jpeg", blob: new Blob(["photo"], { type: "image/jpeg" }) },
    ] });
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "retry later" }), { status });
    await flushPendingChecklists();
    expect(await countPendingChecklists()).toBe(1);
    globalThis.fetch = async () => new Response(JSON.stringify({ verdict: "допущен" }), { status: 200 });
    await flushPendingChecklists();
    expect(await countPendingChecklists()).toBe(0);
  });
}

test("ошибочная разметка формы 422 удаляется с объяснением", async () => {
  await savePendingChecklist({ created_at: new Date().toISOString(), answers: {}, photos: [] });
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "некорректная форма" }), { status: 422 });
  const messages = await flushPendingChecklists();
  expect(await countPendingChecklists()).toBe(0);
  expect(messages[0]).toContain("некорректная форма");
});
