// FINN Progressive Web App Service Worker (P5 Offline Drill)
// Enables full offline functionality when network is disconnected.

const CACHE_NAME = "finn-shell-v1";
const API_CACHE_NAME = "finn-api-v1";

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

  // API Requests: Stale-While-Revalidate with Offline Cache Fallback
  if (url.pathname.startsWith("/api/v1/")) {
    event.respondWith(
      caches.open(API_CACHE_NAME).then((cache) => {
        return fetch(request)
          .then((response) => {
            if (response.status === 200) {
              cache.put(request, response.clone());
            }
            return response;
          })
          .catch(() => {
            // Network failure / Offline mode: serve cached snapshot
            return cache.match(request).then((cachedResponse) => {
              if (cachedResponse) {
                return cachedResponse;
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
            });
          });
      })
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
