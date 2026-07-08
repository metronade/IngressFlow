"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, createCheckout, getMyScrapes, type ScrapeHistoryItem } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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

export default function AccountPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const [history, setHistory] = useState<ScrapeHistoryItem[]>([]);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [upgrading, setUpgrading] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) getMyScrapes().then(setHistory).catch(() => {});
  }, [user]);

  async function handleUpgrade() {
    setUpgradeError(null);
    setUpgrading(true);
    try {
      const { checkout_url } = await createCheckout();
      window.location.href = checkout_url;
    } catch (err) {
      setUpgradeError(
        err instanceof ApiError && err.status === 503
          ? "Billing isn't configured on this deployment yet."
          : "Couldn't start checkout. Please try again.",
      );
      setUpgrading(false);
    }
  }

  if (loading || !user) {
    return <main className="p-8 text-neutral-400">Loading…</main>;
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Account</h1>
        <p className="mt-1 text-neutral-400">
          {user.email} — <span className="uppercase">{user.role}</span> tier
        </p>
      </div>

      {user.role !== "paid" && user.role !== "admin" && (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <p className="mb-3 text-sm text-neutral-400">
            Paid accounts get the full 100-link batch size and no daily scrape cap.
          </p>
          <button
            onClick={handleUpgrade}
            disabled={upgrading}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {upgrading ? "Redirecting…" : "Upgrade to Paid"}
          </button>
          {upgradeError && <p className="mt-2 text-sm text-red-400">{upgradeError}</p>}
        </div>
      )}

      <div>
        <h2 className="mb-3 text-lg font-semibold">Scrape history</h2>
        {history.length === 0 ? (
          <p className="text-neutral-400">No scrapes yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {history.map((h) => (
              <li
                key={h.scrape_id}
                className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm"
              >
                <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs uppercase">{h.status}</span>
                <span className="flex-1 text-neutral-400">{new Date(h.created_at).toLocaleString()}</span>
                <span className="text-neutral-400">
                  {h.total_images} images · {h.total_videos} videos · {formatBytes(h.total_bytes)}
                </span>
                {h.share_token ? (
                  <>
                    <Link href={`/scrape/${h.share_token}`} className="text-neutral-300 hover:text-white">
                      Dashboard
                    </Link>
                    <Link href={`/gallery/${h.share_token}`} className="text-neutral-300 hover:text-white">
                      Gallery
                    </Link>
                  </>
                ) : (
                  <span className="text-neutral-600">expired</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
