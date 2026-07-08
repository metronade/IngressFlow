"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { type CmsPage, getPublicCmsPage } from "@/lib/adminApi";

export default function LegalPage() {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<CmsPage | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    getPublicCmsPage(slug)
      .then(setPage)
      .catch(() => setNotFound(true));
  }, [slug]);

  if (notFound) {
    return (
      <main className="mx-auto max-w-2xl p-8">
        <p className="text-neutral-400">This page hasn&apos;t been published yet.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl p-8">
      {page ? (
        <>
          <h1 className="mb-4 text-2xl font-semibold capitalize">{page.slug}</h1>
          <pre className="whitespace-pre-wrap font-sans text-sm text-neutral-300">{page.content_md}</pre>
        </>
      ) : (
        <p className="text-neutral-400">Loading…</p>
      )}
    </main>
  );
}
