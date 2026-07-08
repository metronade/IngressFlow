"use client";

import { type FormEvent, useEffect, useState } from "react";
import { AdminGuard } from "@/components/AdminGuard";
import { type CmsPage, getCmsPages, upsertCmsPage } from "@/lib/adminApi";

const SUGGESTED_SLUGS = ["impressum", "tos", "privacy"];

function CmsEditor() {
  const [pages, setPages] = useState<CmsPage[]>([]);
  const [slug, setSlug] = useState("impressum");
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState(false);

  function load() {
    getCmsPages().then((loaded) => {
      setPages(loaded);
      const current = loaded.find((p) => p.slug === slug);
      if (current) setContent(current.content_md);
    });
  }

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  function selectSlug(s: string) {
    setSlug(s);
    setContent(pages.find((p) => p.slug === s)?.content_md ?? "");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await upsertCmsPage(slug, content);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
    load();
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Legal pages</h1>
      <p className="text-neutral-400">
        Plain text/Markdown source — rendered as-is on <code>/legal/&lt;slug&gt;</code>, no
        template beyond that.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {SUGGESTED_SLUGS.map((s) => (
          <button
            key={s}
            onClick={() => selectSlug(s)}
            className={`rounded-lg px-3 py-1 text-sm ${slug === s ? "bg-blue-600 text-white" : "bg-neutral-900 text-neutral-300"}`}
          >
            {s}
          </button>
        ))}
        <input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          className="rounded-lg border border-neutral-800 bg-neutral-900 p-1 text-sm"
          placeholder="custom-slug"
        />
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={16}
          className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 font-mono text-sm"
        />
        <div className="flex items-center gap-3">
          <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500">
            Save
          </button>
          {saved && <span className="text-sm text-green-400">Saved.</span>}
          <a href={`/legal/${slug}`} target="_blank" rel="noreferrer" className="text-sm text-neutral-400 hover:text-white">
            View public page →
          </a>
        </div>
      </form>
    </main>
  );
}

export default function CmsPageAdmin() {
  return (
    <AdminGuard>
      <CmsEditor />
    </AdminGuard>
  );
}
