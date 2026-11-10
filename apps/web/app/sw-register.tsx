"use client";

import { useEffect } from "react";

export function SwRegister() {
  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      process.env.NODE_ENV !== "development"
    ) {
      const hadController = Boolean(navigator.serviceWorker.controller);
      let reloading = false;
      const onControllerChange = () => {
        if (hadController && !reloading) {
          reloading = true;
          window.location.reload();
        }
      };
      navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
      navigator.serviceWorker
        .register("/sw.js")
        .then((reg) => reg.update().catch(() => {}))
        .catch(() => {});
      return () => {
        navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
      };
    }
  }, []);

  return null;
}
