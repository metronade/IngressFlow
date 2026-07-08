"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, submitScrape } from "@/lib/api";

const ATTESTATION_TEXT_VERSION = "v1";

const EXAMPLE = `L1234
https://example.com/a
https://example.com/b

L1235
https://example.com/c`;

export default function Home() {
  const router = useRouter();
  const [rawText, setRawText] = useState("");
  const [videoOnly, setVideoOnly] = useState(false);
  const [imageOnly, setImageOnly] = useState(false);
  const [includeMetadata, setIncludeMetadata] = useState(false);
  const [attested, setAttested] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleVideoOnly(checked: boolean) {
    setVideoOnly(checked);
    if (checked) setImageOnly(false);
  }

  function handleImageOnly(checked: boolean) {
    setImageOnly(checked);
    if (checked) setVideoOnly(false);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!attested) {
      setError("You must confirm you hold the rights/lawful basis to ingest this content.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await submitScrape(
        rawText,
        { video_only: videoOnly, image_only: imageOnly, include_metadata: includeMetadata },
        ATTESTATION_TEXT_VERSION,
      );
      router.push(`/scrape/${result.share_token}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">IngressFlow</h1>
        <p className="mt-1 text-neutral-400">
          Paste a category header followed by its links. A blank line or a new header starts the
          next category.
        </p>
      </div>

      <pre className="whitespace-pre-wrap rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm text-neutral-500">
        {EXAMPLE}
      </pre>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          rows={12}
          placeholder={EXAMPLE}
          required
          className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 font-mono text-sm focus:border-neutral-600 focus:outline-none"
        />

        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={videoOnly} onChange={(e) => handleVideoOnly(e.target.checked)} />
            Video only
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={imageOnly} onChange={(e) => handleImageOnly(e.target.checked)} />
            Image only
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeMetadata}
              onChange={(e) => setIncludeMetadata(e.target.checked)}
            />
            Include metadata (JSON)
          </label>
        </div>

        <label className="flex items-start gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm">
          <input
            type="checkbox"
            checked={attested}
            onChange={(e) => setAttested(e.target.checked)}
            required
            className="mt-1"
          />
          <span>
            I confirm I hold the rights or lawful basis to ingest this content for editorial use.
          </span>
        </label>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button
          type="submit"
          disabled={submitting || !attested || rawText.trim().length === 0}
          className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Start scrape"}
        </button>
      </form>
    </main>
  );
}
