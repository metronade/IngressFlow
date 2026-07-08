"use client";

import { type FormEvent, useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import { type AuditEntry, getAuditLog } from "@/lib/adminApi";

function AuditViewer() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [action, setAction] = useState("");
  const [actorIp, setActorIp] = useState("");

  function load(filters?: { action?: string; actor_ip?: string }) {
    getAuditLog(filters).then(setEntries).catch(() => {});
  }

  useEffect(() => load(), []);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    load({ action: action || undefined, actor_ip: actorIp || undefined });
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Audit log</h1>
      <p className="text-neutral-400">Append-only — who started which scrape, when, and from where.</p>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Action</label>
          <input
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="scrape.submitted"
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Actor IP</label>
          <input
            value={actorIp}
            onChange={(e) => setActorIp(e.target.value)}
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500">
          Filter
        </button>
      </form>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-neutral-500">
            <tr>
              <th className="py-2 pr-4">Time</th>
              <th className="py-2 pr-4">Action</th>
              <th className="py-2 pr-4">Actor IP</th>
              <th className="py-2 pr-4">Target</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-t border-neutral-800">
                <td className="py-2 pr-4 text-neutral-400">{new Date(e.ts).toLocaleString()}</td>
                <td className="py-2 pr-4">{e.action}</td>
                <td className="py-2 pr-4 text-neutral-400">{e.actor_ip}</td>
                <td className="py-2 pr-4 text-neutral-400">
                  {e.target_type}
                  {e.target_id ? `:${e.target_id.slice(0, 8)}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {entries.length === 0 && <p className="mt-4 text-neutral-500">No matching entries.</p>}
      </div>
    </main>
  );
}

export default function AuditPage() {
  return (
    <AdminGuard>
      <AuditViewer />
    </AdminGuard>
  );
}
