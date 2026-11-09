"use client";

import { useEffect } from "react";

export function SwRegister() {
  useEffect(() => {
    if (typeof window !== "undefined" && "serviceWorker" in navigator && process.env.NODE_ENV !== "development") {
      navigator.serviceWorker
        .register("/sw.js")
        .then(() => {
          // Registered v2 service worker
        })
        .catch(() => {});
    }
  }, []);

  return null;
}
