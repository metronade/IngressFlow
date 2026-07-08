"use client";

import { type FormEvent, useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import {
  type Credential,
  createCredential,
  deleteCredential,
  getCredentials,
  updateCredential,
} from "@/lib/adminApi";

const KINDS = ["api_key", "oauth_token", "cookie"];

function CredentialsEditor() {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [platform, setPlatform] = useState("");
  const [kind, setKind] = useState(KINDS[0]);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);

  function load() {
    getCredentials().then(setCredentials).catch(() => {});
  }

  useEffect(load, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createCredential({ platform, kind, secret, enabled: true });
      setPlatform("");
      setSecret("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save.");
    }
  }

  async function toggle(c: Credential) {
    await updateCredential(c.id, { enabled: !c.enabled });
    load();
  }

  async function remove(c: Credential) {
    await deleteCredential(c.id);
    load();
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Platform credentials</h1>
      <p className="text-neutral-400">
        An <em>enabled</em> credential is what actually activates a platform&apos;s Tier-1 API path
        instead of the Tier-2 scrape fallback — flip it on here, no redeploy needed.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Platform</label>
          <input
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            placeholder="youtube"
            required
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Kind</label>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Secret</label>
          <input
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            required
            className="w-64 rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500">
          Add
        </button>
      </form>
      {error && <p className="text-sm text-red-400">{error}</p>}

      <ul className="flex flex-col gap-2">
        {credentials.map((c) => (
          <li
            key={c.id}
            className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm"
          >
            <span className="w-28 font-medium">{c.platform}</span>
            <span className="w-28 text-neutral-400">{c.kind}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${c.enabled ? "bg-green-900 text-green-300" : "bg-neutral-800 text-neutral-400"}`}>
              {c.enabled ? "enabled" : "disabled"}
            </span>
            <span className="flex-1" />
            <button onClick={() => toggle(c)} className="text-neutral-300 hover:text-white">
              {c.enabled ? "Disable" : "Enable"}
            </button>
            <button onClick={() => remove(c)} className="text-red-400 hover:text-red-300">
              Delete
            </button>
          </li>
        ))}
        {credentials.length === 0 && <p className="text-neutral-500">No credentials configured.</p>}
      </ul>
    </main>
  );
}

export default function CredentialsPage() {
  return (
    <AdminGuard>
      <CredentialsEditor />
    </AdminGuard>
  );
}
