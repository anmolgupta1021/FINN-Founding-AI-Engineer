// FINN Progressive Web App Service Worker (v4)
// - Network-First for HTML navigations (/, /cost) so new deploys never serve stale chunk URLs
// - Network-First with full-URL query-string caching for /api/v1/*
// - Pre-warms offline fallback for Brief + the 6 dossiers in API cache
// - Cache-First with network fallback for immutable static assets & icons
// - Stale cache purge on version bump (v1/v2/v3 -> v4)

const CACHE_NAME = "finn-shell-v4";
const API_CACHE_NAME = "finn-api-v4";

const STATIC_ASSETS = [
  "/",
  "/cost",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-512-maskable.png",
  "/apple-touch-icon.png",
];

const OFFLINE_API_WARM_URLS = [
  "/api/v1/brief?window_hours=24&as_of=2026-11-06T23%3A59%3A59%2B05%3A30&vol_mult_min=2.0&price_move_min=2.5&portfolio_only=false",
  "/api/v1/dossiers",
  "/api/v1/dossiers/DIXON",
  "/api/v1/dossiers/POLYCAB",
  "/api/v1/dossiers/HDFCBANK",
  "/api/v1/dossiers/SYRMA",
  "/api/v1/dossiers/NAVINFLUOR",
  "/api/v1/dossiers/TITAN",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    Promise.all([
      caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS).catch(() => {})),
      caches.open(API_CACHE_NAME).then((cache) => cache.addAll(OFFLINE_API_WARM_URLS).catch(() => {})),
    ])
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME && key !== API_CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // 1. Network-First for /api/v1/* with full query-string URL as cache key
  if (url.pathname.startsWith("/api/v1/")) {
    event.respondWith(
      (async () => {
        const fullUrl = request.url;
        const cache = await caches.open(API_CACHE_NAME);

        try {
          const networkResponse = await fetch(request);
          if (networkResponse.ok) {
            try {
              await cache.put(new Request(fullUrl), networkResponse.clone());
            } catch {
              // Ignore cache put errors
            }
          }
          return networkResponse;
        } catch {
          const cachedExact = await cache.match(new Request(fullUrl));
          if (cachedExact) return cachedExact;

          const cachedFallback = await cache.match(new Request(url.origin + url.pathname));
          if (cachedFallback) return cachedFallback;

          return new Response(
            JSON.stringify({
              error: "offline",
              message: "Offline mode — no cached snapshot for this request.",
            }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            }
          );
        }
      })()
    );
    return;
  }

  // 2. Network-First for HTML / Page Navigations so fresh deploys never serve stale HTML + 404 chunks
  if (
    request.mode === "navigate" ||
    request.destination === "document" ||
    url.pathname === "/" ||
    url.pathname === "/cost"
  ) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        try {
          const networkResponse = await fetch(request);
          if (networkResponse.ok) {
            try {
              await cache.put(request, networkResponse.clone());
            } catch {
              // Ignore cache put errors
            }
          }
          return networkResponse;
        } catch {
          const cachedPage = await cache.match(request);
          if (cachedPage) return cachedPage;
          const cachedRoot = await cache.match("/");
          if (cachedRoot) return cachedRoot;
          return Response.error();
        }
      })()
    );
    return;
  }

  // 3. Static Assets (/_next/static/*, icons, manifest): Cache first, then network
  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(request);
      if (cached) return cached;

      try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok && url.pathname.startsWith("/_next/static/")) {
          try {
            await cache.put(request, networkResponse.clone());
          } catch {
            // Ignore cache put errors
          }
        }
        return networkResponse;
      } catch {
        return Response.error();
      }
    })()
  );
});
