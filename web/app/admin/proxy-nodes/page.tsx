"use client";

import { type FormEvent, useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import {
  type ProxyNode,
  createProxyNode,
  deleteProxyNode,
  getProxyNodes,
  updateProxyNode,
} from "@/lib/adminApi";

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
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

function StatusPill({ node }: { node: ProxyNode }) {
  if (!node.connected) {
    return <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">disconnected</span>;
  }
  if (node.demoted) {
    return <span className="rounded-full bg-yellow-950 px-2 py-0.5 text-xs text-yellow-300">in cooldown (erroring)</span>;
  }
  return <span className="rounded-full bg-green-950 px-2 py-0.5 text-xs text-green-300">connected</span>;
}

function NewNodeReveal({ name, token, onDismiss }: { name: string; token: string; onDismiss: () => void }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-blue-900 bg-blue-950/30 p-4 text-sm">
      <p className="font-medium text-blue-300">
        Token for &quot;{name}&quot; — shown once, copy it now. It cannot be retrieved again.
      </p>
      <pre className="overflow-x-auto rounded bg-neutral-950 p-3 text-xs text-neutral-300">
        {`# .env.agent on the residential machine (see docker-compose.agent.yml)
GATEWAY_URL=wss://<your-domain>/agent/connect
AGENT_TOKEN=${token}`}
      </pre>
      <button onClick={onDismiss} className="self-start rounded-lg bg-blue-600 px-3 py-1 text-white hover:bg-blue-500">
        Done, I've copied it
      </button>
    </div>
  );
}

function ProxyNodesEditor() {
  const [nodes, setNodes] = useState<ProxyNode[]>([]);
  const [name, setName] = useState("");
  const [priority, setPriority] = useState(100);
  const [reveal, setReveal] = useState<{ name: string; token: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    getProxyNodes().then(setNodes).catch(() => {});
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 10_000); // live status ticks — connected/demoted/bytes change on their own
    return () => clearInterval(id);
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const { token } = await createProxyNode(name, priority);
      setReveal({ name, token });
      setName("");
      setPriority(100);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create node.");
    }
  }

  async function handlePriorityChange(node: ProxyNode, value: number) {
    await updateProxyNode(node.id, { priority: value });
    load();
  }

  async function toggleEnabled(node: ProxyNode) {
    await updateProxyNode(node.id, { enabled: !node.enabled });
    load();
  }

  async function remove(node: ProxyNode) {
    await deleteProxyNode(node.id);
    load();
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Residential nodes</h1>
      <p className="text-neutral-400">
        Self-registering agents (§4.8a) — e.g. a friend&apos;s home Docker box — that dial in over
        WebSocket and relay Tier-2 traffic out through their own network. Lower priority number is
        tried first; a node that starts only erroring is automatically taken out of rotation for a
        cooldown period, no manual action needed.
      </p>

      {reveal && (
        <NewNodeReveal name={reveal.name} token={reveal.token} onDismiss={() => setReveal(null)} />
      )}

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="anna-berlin"
            required
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Priority</label>
          <input
            type="number"
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
            className="w-24 rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500">
          Add node
        </button>
      </form>
      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-neutral-500">
            <tr>
              <th className="py-2 pr-4">Name</th>
              <th className="py-2 pr-4">Priority</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Enabled</th>
              <th className="py-2 pr-4">Last seen</th>
              <th className="py-2 pr-4">Bytes relayed</th>
              <th className="py-2 pr-4" />
            </tr>
          </thead>
          <tbody>
            {nodes.map((n) => (
              <tr key={n.id} className="border-t border-neutral-800">
                <td className="py-2 pr-4 font-medium">{n.name}</td>
                <td className="py-2 pr-4">
                  <input
                    type="number"
                    defaultValue={n.priority}
                    onBlur={(e) => {
                      const value = Number(e.target.value);
                      if (value !== n.priority) handlePriorityChange(n, value);
                    }}
                    className="w-16 rounded border border-neutral-800 bg-neutral-900 p-1 text-sm"
                  />
                </td>
                <td className="py-2 pr-4">
                  <StatusPill node={n} />
                </td>
                <td className="py-2 pr-4">
                  <button onClick={() => toggleEnabled(n)} className="text-neutral-300 hover:text-white">
                    {n.enabled ? "Disable" : "Enable"}
                  </button>
                </td>
                <td className="py-2 pr-4 text-neutral-400">
                  {n.last_seen_at ? new Date(n.last_seen_at).toLocaleString() : "never"}
                </td>
                <td className="py-2 pr-4 text-neutral-400">{formatBytes(n.bytes_relayed)}</td>
                <td className="py-2 pr-4">
                  <button onClick={() => remove(n)} className="text-red-400 hover:text-red-300">
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {nodes.length === 0 && <p className="mt-4 text-neutral-500">No residential nodes registered yet.</p>}
      </div>
    </main>
  );
}

export default function ProxyNodesPage() {
  return (
    <AdminGuard>
      <ProxyNodesEditor />
    </AdminGuard>
  );
}
