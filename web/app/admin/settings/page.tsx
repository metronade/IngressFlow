"use client";

import { type FormEvent, useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import { type Setting, deleteSetting, getSettings, upsertSetting } from "@/lib/adminApi";

const SUGGESTED_KEYS = [
  "limits.public.max_links_per_scrape",
  "limits.public.max_scrapes_per_period",
  "limits.free.max_links_per_scrape",
  "limits.free.max_scrapes_per_period",
  "retention_hours",
  "proxy_enabled",
];

function SettingsEditor() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  function load() {
    getSettings().then(setSettings).catch(() => {});
  }

  useEffect(load, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      // Accept numbers/booleans/JSON if it parses as such, otherwise a plain string.
      let parsed: unknown = value;
      try {
        parsed = JSON.parse(value);
      } catch {
        // keep as raw string
      }
      await upsertSetting(key, parsed);
      setKey("");
      setValue("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save.");
    }
  }

  async function handleDelete(k: string) {
    await deleteSetting(k);
    load();
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <p className="text-neutral-400">
        Overrides the hardcoded fallbacks used across the system (tier limits, retention, the
        proxy kill-switch). Deleting a row reverts to the built-in default — nothing here is
        required to exist.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Key</label>
          <input
            list="suggested-keys"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
          <datalist id="suggested-keys">
            {SUGGESTED_KEYS.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-neutral-500">Value (JSON or plain text)</label>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
            placeholder="42 or true or &quot;text&quot;"
            className="rounded-lg border border-neutral-800 bg-neutral-900 p-2 text-sm"
          />
        </div>
        <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500">
          Save
        </button>
      </form>
      {error && <p className="text-sm text-red-400">{error}</p>}

      <ul className="flex flex-col gap-2">
        {settings.map((s) => (
          <li
            key={s.key}
            className="flex items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm"
          >
            <span className="flex-1 font-mono">{s.key}</span>
            <span className="text-neutral-400">{JSON.stringify(s.value)}</span>
            <button onClick={() => handleDelete(s.key)} className="text-red-400 hover:text-red-300">
              Delete
            </button>
          </li>
        ))}
        {settings.length === 0 && <p className="text-neutral-500">No overrides set — using all defaults.</p>}
      </ul>
    </main>
  );
}

export default function SettingsPage() {
  return (
    <AdminGuard>
      <SettingsEditor />
    </AdminGuard>
  );
}
