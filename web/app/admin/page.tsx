"use client";

import { useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import { type DiskSample, type ProxyStats, type SystemStats, getDiskSamples, getProxyStats, getSystemStats } from "@/lib/adminApi";

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

function AdminOverview() {
  const [system, setSystem] = useState<SystemStats | null>(null);
  const [disk, setDisk] = useState<DiskSample[]>([]);
  const [proxy, setProxy] = useState<ProxyStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSystemStats().then(setSystem).catch(() => {});
    getDiskSamples().then(setDisk).catch(() => {});
    getProxyStats()
      .then(setProxy)
      .catch((err) => setError(err.message));
  }, []);

  const latest = disk.at(-1);

  return (
    <main className="flex flex-col gap-8">
      <h1 className="text-2xl font-semibold">Admin overview</h1>

      <section>
        <h2 className="mb-3 text-lg font-semibold">System</h2>
        {system ? (
          <div className="grid grid-cols-2 gap-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4 sm:grid-cols-4">
            <Stat label="CPU" value={`${system.cpu_percent.toFixed(1)}%`} />
            <Stat label="Memory" value={`${system.memory_percent.toFixed(1)}%`} />
            <Stat label="Disk used" value={formatBytes(system.disk_used)} />
            <Stat label="Disk free" value={formatBytes(system.disk_free)} />
          </div>
        ) : (
          <p className="text-neutral-400">Loading…</p>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Disk-full forecast</h2>
        {latest ? (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <p className="text-sm text-neutral-400">
              Last sample: {new Date(latest.ts).toLocaleString()} — free {formatBytes(latest.free_bytes)}
            </p>
            <p className="mt-1 text-lg font-semibold">
              {latest.hours_to_full != null
                ? `~${latest.hours_to_full.toFixed(1)} hours to full at current rate`
                : "Stable — deletion rate keeping pace with new data"}
            </p>
            <p className="mt-1 text-xs text-neutral-500">
              in {formatBytes(latest.bytes_in_rate)}/h · out {formatBytes(latest.bytes_out_rate)}/h
            </p>
          </div>
        ) : (
          <p className="text-neutral-400">No samples yet — the hourly predictor hasn't run.</p>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Proxy gateway</h2>
        {error ? (
          <p className="text-red-400">{error}</p>
        ) : proxy ? (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm">
            <p className="mb-2 text-neutral-400">
              {proxy.exits.length === 0
                ? "No exits configured — Tier-2 traffic uses direct passthrough."
                : `${proxy.exits.filter((e) => e.healthy).length}/${proxy.exits.length} exits healthy`}
            </p>
            <p className="text-neutral-500">{Object.keys(proxy.sessions).length} session(s) tracked</p>
          </div>
        ) : (
          <p className="text-neutral-400">Loading…</p>
        )}
      </section>
    </main>
  );
}

export default function AdminPage() {
  return (
    <AdminGuard>
      <AdminOverview />
    </AdminGuard>
  );
}
