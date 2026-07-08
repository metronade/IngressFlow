"use client";

import { useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import { type PlatformHealth, getPlatformHealth } from "@/lib/adminApi";

function PlatformHealthView() {
  const [rows, setRows] = useState<PlatformHealth[]>([]);

  useEffect(() => {
    getPlatformHealth().then(setRows).catch(() => {});
  }, []);

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Platform health</h1>
      <p className="text-neutral-400">
        Success rates per platform, and the API-vs-scrape-fallback mix — a shift toward Playwright
        or a drop in success rate usually means a site changed something.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-neutral-500">
            <tr>
              <th className="py-2 pr-4">Platform</th>
              <th className="py-2 pr-4">Total</th>
              <th className="py-2 pr-4">Success</th>
              <th className="py-2 pr-4">Partial</th>
              <th className="py-2 pr-4">Failed</th>
              <th className="py-2 pr-4">Pending</th>
              <th className="py-2 pr-4">Source methods</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.platform} className="border-t border-neutral-800">
                <td className="py-2 pr-4 font-medium">{r.platform}</td>
                <td className="py-2 pr-4">{r.total_items}</td>
                <td className="py-2 pr-4 text-green-400">{r.success}</td>
                <td className="py-2 pr-4 text-yellow-400">{r.partial}</td>
                <td className="py-2 pr-4 text-red-400">{r.failed}</td>
                <td className="py-2 pr-4 text-neutral-500">{r.pending_or_scraping}</td>
                <td className="py-2 pr-4 text-neutral-400">
                  {Object.entries(r.source_method_counts)
                    .map(([method, count]) => `${method}:${count}`)
                    .join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="mt-4 text-neutral-500">No scrape items yet.</p>}
      </div>
    </main>
  );
}

export default function PlatformsPage() {
  return (
    <AdminGuard>
      <PlatformHealthView />
    </AdminGuard>
  );
}
