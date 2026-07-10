"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import {
  type Category,
  exportSelected,
  exportUrl,
  getCategories,
  getMedia,
  getShareStatus,
  type MediaFile,
  mediaFileUrl,
} from "@/lib/api";
import { ExpiryBanner } from "@/components/ExpiryBanner";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function GalleryContent() {
  const { token } = useParams<{ token: string }>();
  const searchParams = useSearchParams();

  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [itemId, setItemId] = useState(searchParams.get("item") ?? "");
  const [media, setMedia] = useState<MediaFile[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<MediaFile | null>(null);
  const [exporting, setExporting] = useState(false);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);

  useEffect(() => {
    getCategories(token)
      .then(setCategories)
      .catch(() => {});
    getShareStatus(token)
      .then((s) => setExpiresAt(s.expires_at))
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    setLoading(true);
    getMedia(token, { categoryId: categoryId || undefined, itemId: itemId || undefined })
      .then(setMedia)
      .catch(() => setMedia([]))
      .finally(() => setLoading(false));
  }, [token, categoryId, itemId]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function downloadSelected() {
    if (selected.size === 0) return;
    setExporting(true);
    try {
      const blob = await exportSelected(token, Array.from(selected));
      triggerDownload(blob, "ingressflow-selection.zip");
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Gallery</h1>

      {expiresAt && <ExpiryBanner expiresAt={expiresAt} />}

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={itemId ? "" : categoryId}
          onChange={(e) => {
            setItemId("");
            setCategoryId(e.target.value);
          }}
          className="rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        {itemId && (
          <span className="flex items-center gap-2 rounded-lg bg-neutral-800 px-3 py-2 text-sm">
            Filtered to one link
            <button onClick={() => setItemId("")} className="text-neutral-400 hover:text-neutral-200">
              ×
            </button>
          </span>
        )}

        <a
          href={exportUrl(token, { categoryId: categoryId || undefined, itemId: itemId || undefined })}
          className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-500"
        >
          Download this view (ZIP)
        </a>

        <button
          onClick={downloadSelected}
          disabled={selected.size === 0 || exporting}
          className="rounded-lg border border-neutral-700 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          {exporting ? "Preparing…" : `Download selected (${selected.size})`}
        </button>
      </div>

      {loading ? (
        <p className="text-neutral-400">Loading…</p>
      ) : media.length === 0 ? (
        <p className="text-neutral-400">No media in this view.</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
          {media.map((m) => (
            <div key={m.id} className="flex flex-col gap-2 rounded-lg border border-neutral-800 bg-neutral-900 p-2">
              <label className="flex items-center gap-2 text-xs text-neutral-400">
                <input type="checkbox" checked={selected.has(m.id)} onChange={() => toggleSelect(m.id)} />
                <span className="truncate">{m.category_name}</span>
              </label>
              <button onClick={() => setPreview(m)} className="block overflow-hidden rounded">
                {m.type === "image" ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaFileUrl(token, m.id)}
                    alt=""
                    className="aspect-square w-full object-cover transition hover:opacity-80"
                  />
                ) : (
                  <video src={mediaFileUrl(token, m.id)} className="aspect-square w-full object-cover" muted />
                )}
              </button>
            </div>
          ))}
        </div>
      )}

      {preview && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-8"
          onClick={() => setPreview(null)}
        >
          <button
            onClick={() => setPreview(null)}
            className="absolute right-6 top-6 text-2xl text-neutral-300 hover:text-white"
            aria-label="Close preview"
          >
            ×
          </button>
          {preview.type === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaFileUrl(token, preview.id)}
              alt=""
              className="max-h-full max-w-full object-contain"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <video
              src={mediaFileUrl(token, preview.id)}
              controls
              autoPlay
              className="max-h-full max-w-full"
              onClick={(e) => e.stopPropagation()}
            />
          )}
        </div>
      )}
    </main>
  );
}

export default function GalleryPage() {
  return (
    <Suspense fallback={<main className="p-8 text-neutral-400">Loading…</main>}>
      <GalleryContent />
    </Suspense>
  );
}
