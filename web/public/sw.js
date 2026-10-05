/* DriverGuard PWA — service worker (APP-8: кэш оболочки).
   Навигации /driver/* — сеть, при обрыве — кэш той же страницы или /driver/offline.
   Статика Next и иконки — кэш, при промахе — сеть. API живёт на другом origin и не кэшируется. */
const CACHE = "dg-shell-v2";
const PRECACHE = ["/driver/offline", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate" && (url.pathname === "/driver" || url.pathname.startsWith("/driver/"))) {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          // Кэшируем только удачные ответы своего origin: страница 502 от туннеля во время
          // пересборки web не должна навсегда подменить оболочку PWA
          if (resp.ok && resp.type === "basic") {
            const copy = resp.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
          }
          return resp;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match("/driver/offline"))),
    );
    return;
  }
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((resp) => {
            if (resp.ok && resp.type === "basic") {
              const copy = resp.clone();
              caches.open(CACHE).then((cache) => cache.put(req, copy));
            }
            return resp;
          }),
      ),
    );
  }
});
