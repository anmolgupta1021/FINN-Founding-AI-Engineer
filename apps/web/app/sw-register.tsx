"use client";

import { useEffect } from "react";

export function SwRegister() {
  useEffect(() => {
    if (typeof window !== "undefined" && "serviceWorker" in navigator && process.env.NODE_ENV !== "development") {
      navigator.serviceWorker
        .register("/sw.js")
        .then((reg) => {
          // Pre-populate core API snapshot caches for immediate offline drill readiness
          if (reg.active) {
            const coreEndpoints = [
              "/api/v1/health",
              "/api/v1/brief?window_hours=24",
              "/api/v1/dossiers/DIXON",
              "/api/v1/dossiers/SYRMA",
              "/api/v1/dossiers/NAVINFLUOR",
              "/api/v1/dossiers/POLYCAB",
              "/api/v1/dossiers/HDFCBANK",
              "/api/v1/dossiers/TITAN",
              "/api/v1/network/ask?q=specialty+chemicals",
              "/api/v1/llm/ledger",
            ];
            coreEndpoints.forEach((ep) => {
              fetch(ep).catch(() => {});
            });
          }
        })
        .catch(() => {});
    }
  }, []);

  return null;
}
