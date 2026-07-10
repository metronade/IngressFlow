"use client";

import { useEffect, useState } from "react";

function formatRemaining(ms: number): string {
  if (ms <= 0) return "any moment now";
  const totalMinutes = Math.round(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

// expiresAt reflects each scrape's own Scrape.expires_at, computed at
// submission time from whatever retention_hours was set then (admin-
// tunable, PLAN.md §9 Phase 5) — never hardcoded, and unaffected if the
// setting changes later since it's baked into that one row.
export function ExpiryBanner({ expiresAt }: { expiresAt: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  const remainingMs = new Date(expiresAt).getTime() - now;
  const expired = remainingMs <= 0;

  return (
    <p className="rounded-lg border border-yellow-900 bg-yellow-950/40 px-3 py-2 text-sm text-yellow-300">
      {expired
        ? "This content has expired and will be removed shortly."
        : `This content will be deleted in ${formatRemaining(remainingMs)} (at ${new Date(expiresAt).toLocaleString()}).`}
    </p>
  );
}
