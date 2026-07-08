import { getToken } from "@/lib/token";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}) as { detail?: unknown });
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// -- settings --------------------------------------------------------------

export type Setting = { key: string; value: unknown };

export function getSettings() {
  return adminRequest<Setting[]>("/api/admin/settings");
}

export function upsertSetting(key: string, value: unknown) {
  return adminRequest<Setting>(`/api/admin/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

export function deleteSetting(key: string) {
  return adminRequest<void>(`/api/admin/settings/${encodeURIComponent(key)}`, { method: "DELETE" });
}

// -- platform credentials ---------------------------------------------------

export type Credential = {
  id: string;
  platform: string;
  kind: string;
  enabled: boolean;
  valid_until: string | null;
  created_at: string;
};

export function getCredentials() {
  return adminRequest<Credential[]>("/api/admin/credentials");
}

export function createCredential(data: { platform: string; kind: string; secret: string; enabled: boolean }) {
  return adminRequest<Credential>("/api/admin/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function updateCredential(id: string, data: { enabled?: boolean }) {
  return adminRequest<Credential>(`/api/admin/credentials/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deleteCredential(id: string) {
  return adminRequest<void>(`/api/admin/credentials/${id}`, { method: "DELETE" });
}

// -- disk-full predictor -----------------------------------------------------

export type DiskSample = {
  ts: string;
  free_bytes: number;
  bytes_in_rate: number;
  bytes_out_rate: number;
  hours_to_full: number | null;
};

export function getDiskSamples() {
  return adminRequest<DiskSample[]>("/api/admin/disk");
}

// -- audit log ---------------------------------------------------------------

export type AuditEntry = {
  id: string;
  ts: string;
  actor_user_id: string | null;
  actor_ip: string;
  action: string;
  target_type: string;
  target_id: string | null;
  detail: Record<string, unknown> | null;
};

export function getAuditLog(params?: { action?: string; actor_ip?: string }) {
  const qs = new URLSearchParams();
  if (params?.action) qs.set("action", params.action);
  if (params?.actor_ip) qs.set("actor_ip", params.actor_ip);
  const q = qs.toString();
  return adminRequest<AuditEntry[]>(`/api/admin/audit${q ? `?${q}` : ""}`);
}

// -- per-platform health ------------------------------------------------------

export type PlatformHealth = {
  platform: string;
  total_items: number;
  success: number;
  partial: number;
  failed: number;
  pending_or_scraping: number;
  source_method_counts: Record<string, number>;
};

export function getPlatformHealth() {
  return adminRequest<PlatformHealth[]>("/api/admin/platform-health");
}

// -- system + proxy -----------------------------------------------------------

export type SystemStats = {
  cpu_percent: number;
  memory_percent: number;
  disk_total: number;
  disk_used: number;
  disk_free: number;
};

export function getSystemStats() {
  return adminRequest<SystemStats>("/api/admin/system");
}

export type ProxyStats = {
  exits: { name: string; healthy: boolean }[];
  sessions: Record<string, { bytes_up: number; bytes_down: number; requests: number; exit: string | null }>;
};

export function getProxyStats() {
  return adminRequest<ProxyStats>("/api/admin/proxy-stats");
}

// -- CMS -----------------------------------------------------------------------

export type CmsPage = { slug: string; content_md: string; updated_at: string };

export function getCmsPages() {
  return adminRequest<CmsPage[]>("/api/admin/cms");
}

export function upsertCmsPage(slug: string, content_md: string) {
  return adminRequest<CmsPage>(`/api/admin/cms/${encodeURIComponent(slug)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_md }),
  });
}

export async function getPublicCmsPage(slug: string): Promise<CmsPage> {
  const res = await fetch(`${API_BASE}/api/cms/${encodeURIComponent(slug)}`);
  if (!res.ok) throw new Error("Not found");
  return res.json();
}
