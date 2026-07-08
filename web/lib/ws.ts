"use client";

import { useEffect, useRef, useState } from "react";

function wsBase(): string {
  if (process.env.NEXT_PUBLIC_WS_BASE) return process.env.NEXT_PUBLIC_WS_BASE;
  if (typeof window === "undefined") return "";
  // Same-origin fallback — correct in prod, where NPM fronts /ws on the same
  // domain as the page itself (PLAN.md §4.4/§2). Only dev needs an override,
  // since there's no NPM in front of the raw docker compose ports.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

export type ProgressSnapshot = {
  scrape_id: string;
  status: string;
  links_done: number;
  links_total: number;
  total_images: number;
  total_videos: number;
  total_bytes: number;
};

type ServerEvent =
  | { type: "progress"; data: ProgressSnapshot }
  | { type: "done" }
  | { type: "error"; detail: string };

export function useShareSocket(token: string) {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);
  const [done, setDone] = useState(false);
  const [expired, setExpired] = useState(false);
  const retryCount = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(`${wsBase()}/ws/share/${token}`);

      ws.onopen = () => {
        retryCount.current = 0;
      };

      ws.onmessage = (event) => {
        const msg: ServerEvent = JSON.parse(event.data);
        if (msg.type === "progress") setSnapshot(msg.data);
        else if (msg.type === "done") setDone(true);
        else if (msg.type === "error") setExpired(true);
      };

      ws.onclose = (event) => {
        if (cancelled || event.code === 4410) return; // 4410: expired, PLAN.md §4.5 — don't retry
        const delay = Math.min(1000 * 2 ** retryCount.current, 10000);
        retryCount.current += 1;
        retryTimer = setTimeout(connect, delay);
      };
    }

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      ws?.close();
    };
  }, [token]);

  return { snapshot, done, expired };
}
