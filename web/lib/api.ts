import { getToken } from "@/lib/token";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}) as { detail?: unknown });
    // fastapi-users sometimes returns a structured object (e.g.
    // {code, reason}) instead of a plain string for validation errors.
    const detail = body.detail;
    const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export type ScrapeConfig = {
  video_only: boolean;
  image_only: boolean;
  include_metadata: boolean;
};

export type SubmitResponse = {
  scrape_id: string;
  share_token: string;
  status: string;
  links_total: number;
};

export function submitScrape(rawText: string, config: ScrapeConfig, attestationVersion: string) {
  return request<SubmitResponse>("/api/scrapes", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      raw_text: rawText,
      config,
      attestation: { accepted: true, text_version: attestationVersion },
    }),
  });
}

// -- auth (PLAN.md §9 Phase 4) --------------------------------------------

export type UserRead = {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  role: "public" | "free" | "paid" | "admin";
  credit_balance: number;
};

export async function login(email: string, password: string): Promise<{ access_token: string }> {
  const res = await fetch(`${API_BASE}/api/auth/jwt/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}) as { detail?: string });
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : "Login failed.");
  }
  return res.json();
}

export function register(email: string, password: string) {
  return request<UserRead>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function getMe() {
  return request<UserRead>("/api/users/me", { headers: authHeaders() });
}

export type ScrapeHistoryItem = {
  scrape_id: string;
  status: string;
  share_token: string | null;
  total_images: number;
  total_videos: number;
  total_bytes: number;
  created_at: string;
  expires_at: string;
};

export function getMyScrapes() {
  return request<ScrapeHistoryItem[]>("/api/me/scrapes", { headers: authHeaders() });
}

export function createCheckout() {
  return request<{ checkout_url: string }>("/api/billing/checkout", {
    method: "POST",
    headers: authHeaders(),
  });
}

export function cancelScrape(scrapeId: string) {
  return request<{ status: string }>(`/api/scrapes/${scrapeId}/cancel`, { method: "POST" });
}

export type ShareItem = {
  id: string;
  url: string;
  platform: string | null;
  status: string;
  images_found: number;
  images_ok: number;
  videos_found: number;
  videos_ok: number;
  error: string | null;
};

export type ShareStatus = {
  scrape_id: string;
  status: string;
  total_images: number;
  total_videos: number;
  total_bytes: number;
  expires_at: string;
  items: ShareItem[];
};

export function getShareStatus(token: string) {
  return request<ShareStatus>(`/api/share/${token}`);
}

export type Category = { id: string; name: string; order: number };

export function getCategories(token: string) {
  return request<Category[]>(`/api/share/${token}/categories`);
}

export type MediaFile = {
  id: string;
  item_id: string;
  category_id: string;
  category_name: string;
  type: "image" | "video";
  bytes: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  source_url: string;
  source_method: string;
};

export function getMedia(token: string, opts?: { categoryId?: string; itemId?: string }) {
  const params = new URLSearchParams();
  if (opts?.categoryId) params.set("category_id", opts.categoryId);
  if (opts?.itemId) params.set("item_id", opts.itemId);
  const qs = params.toString();
  return request<MediaFile[]>(`/api/share/${token}/media${qs ? `?${qs}` : ""}`);
}

export function mediaFileUrl(token: string, mediaId: string): string {
  return `${API_BASE}/api/share/${token}/media/${mediaId}/file`;
}

export function exportUrl(token: string, opts?: { categoryId?: string; itemId?: string }): string {
  const params = new URLSearchParams();
  if (opts?.categoryId) params.set("category_id", opts.categoryId);
  if (opts?.itemId) params.set("item_id", opts.itemId);
  const qs = params.toString();
  return `${API_BASE}/api/share/${token}/export${qs ? `?${qs}` : ""}`;
}

export async function exportSelected(token: string, mediaIds: string[]): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/share/${token}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_ids: mediaIds }),
  });
  if (!res.ok) throw new ApiError(res.status, "Export failed");
  return res.blob();
}
