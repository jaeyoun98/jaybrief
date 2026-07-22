"use strict";

// Bump VERSION whenever any shell file changes so installed clients update.
const VERSION = "v1.8";
const SHELL_CACHE = `shell-${VERSION}`;
const SHELL = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // cache:"reload" bypasses the HTTP cache so a VERSION bump can't be
      // populated from stale copies still inside GitHub Pages' 10-min max-age
      .then((cache) => cache.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.includes("/data/") || url.pathname.endsWith("/events.json") || url.pathname.endsWith("/companies.json")) {
    // Data: network first with ETag revalidation (GitHub Pages caches 10 min),
    // cached copy only as offline fallback.
    event.respondWith(
      fetch(event.request, { cache: "no-cache" })
        .then((resp) => {
          if (resp.ok) {
            // never cache error responses — they would poison the offline fallback
            const copy = resp.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, copy));
          }
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
  } else {
    // Shell: cache first; updates arrive via VERSION bump.
    event.respondWith(
      caches.match(event.request).then((hit) => hit || fetch(event.request))
    );
  }
});
