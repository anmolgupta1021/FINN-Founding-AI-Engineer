// FINN Progressive Web App Service Worker (v2)
// Network-First with full-URL query-string caching for API calls.
// Stale cache purge on version bump.

const CACHE_NAME = "finn-shell-v2";
const API_CACHE_NAME = "finn-api-v2";

const STATIC_ASSETS = [
  "/",
  "/cost",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-512-maskable.png",
  "/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
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
  const url = new URL(request.url);

  // Network-First for /api/v1/brief and all /api/v1/* calls with full query-string URL as cache key
  if (url.pathname.startsWith("/api/v1/")) {
    event.respondWith(
      (async () => {
        const fullUrl = request.url;
        const cache = await caches.open(API_CACHE_NAME);

        try {
          // Network-first: fetch live data from server
          const networkResponse = await fetch(request);
          if (networkResponse.status === 200) {
            // Store using clean Request object without no-store restrictions
            try {
              await cache.put(new Request(fullUrl), networkResponse.clone());
            } catch {
              // Ignore cache put errors if browser restricts certain headers
            }
          }
          return networkResponse;
        } catch {
          // Offline / network failure: match exact full URL with query string
          const cachedExact = await cache.match(new Request(fullUrl));
          if (cachedExact) {
            return cachedExact;
          }

          // If offline and exact window not cached, attempt matching without query as best effort
          const cachedFallback = await cache.match(new Request(url.origin + url.pathname));
          if (cachedFallback) {
            return cachedFallback;
          }

          return new Response(
            JSON.stringify({
              error: "offline",
              message: "Offline mode — using cached primary data.",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }
          );
        }
      })()
    );
    return;
  }

  // App Shell Navigation & Static Assets: Cache first, then network fallback
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).catch(() => {
        if (request.mode === "navigate") {
          return caches.match("/");
        }
      });
    })
  );
});
