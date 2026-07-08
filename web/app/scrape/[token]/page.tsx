"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { cancelScrape, getShareStatus, type ShareStatus } from "@/lib/api";
import { useShareSocket } from "@/lib/ws";

function statusColor(status: string): string {
  switch (status) {
    case "success":
      return "bg-green-500";
    case "partial":
      return "bg-yellow-500";
    case "failed":
      return "bg-red-500";
    case "scraping":
      return "bg-blue-500 animate-pulse";
    default:
      return "bg-neutral-600";
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(2)} ${units[unit]}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

export default function ScrapeDashboard() {
  const { token } = useParams<{ token: string }>();
  const { snapshot, done, expired } = useShareSocket(token);
  const [status, setStatus] = useState<ShareStatus | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [notified, setNotified] = useState(false);

  useEffect(() => {
    getShareStatus(token)
      .then(setStatus)
      .catch(() => {});
  }, [token]);

  // WS pushes aggregate counters only; refetch the per-item list whenever a
  // progress event lands. Cheap at this scale (max 100 items per batch).
  useEffect(() => {
    if (!snapshot) return;
    getShareStatus(token)
      .then(setStatus)
      .catch(() => {});
  }, [snapshot, token]);

  useEffect(() => {
    if (!done || notified || typeof window === "undefined" || !("Notification" in window)) return;
    setNotified(true);

    const fire = () => new Notification("IngressFlow", { body: "Your scrape has finished." });
    if (Notification.permission === "granted") fire();
    else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((perm) => {
        if (perm === "granted") fire();
      });
    }
  }, [done, notified]);

  async function handleCopy(url: string, id: string) {
    await navigator.clipboard.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  }

  async function handleCancel() {
    if (!status) return;
    await cancelScrape(status.scrape_id);
  }

  if (expired) {
    return (
      <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-4 p-8">
        <h1 className="text-2xl font-semibold">Link expired</h1>
        <p className="text-neutral-400">This share link is no longer available.</p>
      </main>
    );
  }

  const linksDone = snapshot?.links_done ?? status?.items.filter((i) => i.status !== "pending").length ?? 0;
  const linksTotal = snapshot?.links_total ?? status?.items.length ?? 0;
  const currentStatus = snapshot?.status ?? status?.status ?? "queued";
  const isRunning = currentStatus === "queued" || currentStatus === "running";

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Scrape progress</h1>

      <div className="grid grid-cols-2 gap-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4 sm:grid-cols-4">
        <Stat label="Links" value={`${linksDone} / ${linksTotal}`} />
        <Stat label="Images" value={String(snapshot?.total_images ?? status?.total_images ?? 0)} />
        <Stat label="Videos" value={String(snapshot?.total_videos ?? status?.total_videos ?? 0)} />
        <Stat label="Total size" value={formatBytes(snapshot?.total_bytes ?? status?.total_bytes ?? 0)} />
      </div>

      <div className="flex items-center gap-3">
        <span className="rounded-full bg-neutral-800 px-3 py-1 text-sm capitalize">{currentStatus}</span>
        {isRunning ? (
          <button
            onClick={handleCancel}
            className="rounded-lg border border-red-900 px-3 py-1 text-sm text-red-400 hover:bg-red-950"
          >
            Cancel
          </button>
        ) : (
          <Link href={`/gallery/${token}`} className="rounded-lg bg-blue-600 px-3 py-1 text-sm text-white">
            View gallery
          </Link>
        )}
      </div>

      <ul className="flex flex-col gap-2">
        {status?.items.map((item) => (
          <li
            key={item.id}
            className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm"
          >
            <span className={`h-3 w-3 shrink-0 rounded-full ${statusColor(item.status)}`} title={item.status} />
            <span className="flex-1 truncate" title={item.url}>
              {item.url}
            </span>
            <span className="shrink-0 text-neutral-400">
              {item.images_ok}/{item.images_found} images · {item.videos_ok}/{item.videos_found} videos
            </span>
            <Link
              href={`/gallery/${token}?item=${item.id}`}
              className="shrink-0 text-neutral-400 hover:text-neutral-200"
            >
              View
            </Link>
            <button
              onClick={() => handleCopy(item.url, item.id)}
              className="shrink-0 text-neutral-400 hover:text-neutral-200"
            >
              {copiedId === item.id ? "Copied" : "Copy link"}
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
