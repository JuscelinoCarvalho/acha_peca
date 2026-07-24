/* Service worker do acha peça (PWA).
   - App shell (estáticos) em cache-first para abrir offline e instantâneo.
   - Chamadas /api/* em network-first com fallback ao cache (último resultado). */
const VERSION = "achapeca-v18";
const SHELL = ["/", "/assets/style.css", "/assets/app.js", "/assets/icon.svg", "/manifest.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const { request } = e;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;  // não intercepta terceiros (AdSense, Google)
  if (url.pathname.startsWith("/manuais/")) return;  // manuais (PDF/RAR grandes): rede direta, nunca cacheia
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(
      fetch(request).then(res => {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(request, copy));
        return res;
      }).catch(() => caches.match(request))
    );
  } else {
    e.respondWith(
      caches.match(request).then(hit => hit || fetch(request).then(res => {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(request, copy));
        return res;
      }).catch(() => caches.match("/")))
    );
  }
});
