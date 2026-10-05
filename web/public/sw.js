/* APP-8: camera + model files, separate from API/user data. The last complete
   bundle stays available if an update fails halfway. */
const RUNTIME = "dg-shell-v3";
const META = "dg-offline-meta-v1";
const STATE = "/__dg_offline_state";
const DOCUMENTS = ["/driver/camera", "/driver/offline"];
let preparation = null;
const allowedAsset = (path) => /^\/(?:_next\/static\/|mediapipe\/wasm\/|onnx\/1\.22\.0\/|models\/|icons\/)/.test(path) || path === "/manifest.webmanifest";

async function state() {
  const response = await (await caches.open(META)).match(STATE);
  return response ? response.json() : null;
}
async function prepared(path) {
  const current = await state();
  return current ? (await caches.open(current.cache)).match(path, { ignoreVary: true }) : undefined;
}
async function status() {
  const current = await state();
  if (!current) return { ready: false };
  const cache = await caches.open(current.cache);
  for (const url of current.urls) if (!(await cache.match(url, { ignoreVary: true }))) return { ready: false };
  return { ready: true, version: current.version, savedAt: current.savedAt, objectModel: current.objectModel };
}
async function sha256(response) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await response.clone().arrayBuffer())), (b) => b.toString(16).padStart(2, "0")).join("");
}
async function checkedFetch(url, expected) {
  const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(90_000) });
  if (!response.ok || response.type === "opaque" || response.redirected) throw new Error(`Не загружен файл: ${url}`);
  if (expected && (await response.clone().arrayBuffer()).byteLength !== expected.bytes) throw new Error(`Неполный файл: ${url}`);
  if (expected && await sha256(response) !== expected.sha256) throw new Error(`Файл изменился. Обновите страницу и повторите: ${url}`);
  return response;
}
async function prepare(port) {
  const manifest = await (await checkedFetch("/offline-assets.json")).json();
  if (!/^[a-zA-Z0-9_-]+$/.test(manifest.version) || !Array.isArray(manifest.assets) || manifest.assets.length < 5) throw new Error("Нет списка файлов для офлайн-режима. Обновите сборку приложения.");
  if (manifest.missing?.length) throw new Error("На сервере отсутствуют модели камеры. Требуется завершить установку.");
  const entries = [...manifest.assets];
  let objectModel = false;
  const modelResponse = await fetch("/models/browser-model.json", { cache: "no-store", signal: AbortSignal.timeout(15_000) });
  let modelManifest;
  if (modelResponse.ok) {
    modelManifest = await modelResponse.clone().json();
    if (!/^\/models\/[a-zA-Z0-9_-]+\.onnx$/.test(modelManifest.model_url) || !/^[a-f0-9]{64}$/i.test(modelManifest.sha256)) throw new Error("Некорректное описание модели предметов.");
    entries.push({ url: modelManifest.model_url }, { url: "/onnx/1.22.0/ort-wasm-simd-threaded.wasm" }, { url: "/onnx/1.22.0/ort-wasm-simd-threaded.mjs" });
    objectModel = true;
  } else if (modelResponse.status !== 404) throw new Error("Не удалось проверить модель предметов. Повторите подготовку.");
  const name = `dg-offline-${manifest.version}-${Date.now()}`;
  const cache = await caches.open(name);
  const urls = [];
  try {
    for (const entry of entries) {
      if (typeof entry.url !== "string" || !entry.url.startsWith("/") || entry.url.startsWith("//") || entry.url.includes("..") || !allowedAsset(entry.url)) throw new Error("Недопустимый путь в списке файлов.");
      const response = await checkedFetch(entry.url, entry.sha256 ? entry : undefined);
      if (entry.url === modelManifest?.model_url && await sha256(response) !== modelManifest.sha256) throw new Error("Модель предметов не прошла проверку целостности.");
      await cache.put(entry.url, response);
      urls.push(entry.url);
      port?.postMessage({ progress: Math.min(99, Math.round(urls.length / (entries.length + DOCUMENTS.length) * 100)) });
    }
    if (objectModel) { await cache.put("/models/browser-model.json", modelResponse); urls.push("/models/browser-model.json"); }
    for (const url of DOCUMENTS) {
      const response = await checkedFetch(url);
      if (!response.headers.get("content-type")?.includes("text/html")) throw new Error("Не удалось сохранить экран камеры.");
      const html = await response.clone().text();
      for (const match of html.matchAll(/(?:src|href)="([^"?#]+)[^"]*"/g)) {
        if (match[1].startsWith("/_next/static/") && !urls.includes(match[1])) throw new Error("Сборка обновилась. Повторите подготовку.");
      }
      await cache.put(url, response);
      urls.push(url);
    }
    const current = { cache: name, version: manifest.version, urls, savedAt: new Date().toISOString(), objectModel };
    await (await caches.open(META)).put(STATE, new Response(JSON.stringify(current), { headers: { "Content-Type": "application/json" } }));
    for (const key of await caches.keys()) if (key.startsWith("dg-offline-") && key !== META && key !== name) await caches.delete(key);
    return { ready: true, ...current };
  } catch (error) { await caches.delete(name); throw error; }
}
self.addEventListener("install", (event) => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("message", (event) => {
  const port = event.ports[0];
  if (!port || !["DG_OFFLINE_STATUS", "DG_OFFLINE_PREPARE"].includes(event.data?.type)) return;
  event.waitUntil((async () => {
    try {
      if (event.data.type === "DG_OFFLINE_PREPARE") {
        if (preparation) throw new Error("Подготовка уже идёт в другой вкладке.");
        preparation = prepare(port);
        try { port.postMessage({ done: await preparation }); } finally { preparation = null; }
      } else port.postMessage({ done: await status() });
    } catch (error) { port.postMessage({ error: error.message || "Не удалось сохранить файлы на телефон." }); }
  })());
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  const navigation = request.mode === "navigate" && (url.pathname === "/driver" || url.pathname.startsWith("/driver/"));
  if (!navigation && !allowedAsset(url.pathname)) return; // Never intercept API or RSC.
  event.respondWith((async () => {
    const cache = await caches.open(RUNTIME);
    const hit = await prepared(navigation ? url.pathname : request) || await cache.match(request, { ignoreVary: true });
    if (!navigation && !url.pathname.startsWith("/models/") && hit) return hit;
    try {
      const response = await fetch(request);
      if (response.ok && !response.redirected) {
        event.waitUntil(cache.put(request, response.clone()).catch(() => undefined));
        return response;
      }
      if (response.status >= 500 && hit) return hit;
      return response;
    } catch {
      if (hit) return hit;
      if (navigation) return await prepared("/driver/offline") || new Response("Нет сети. Откройте камеру с интернетом и нажмите «Подготовить офлайн».", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
      return new Response("Offline file unavailable", { status: 503 });
    }
  })());
});
