"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, login, register } from "@/lib/api";
import { friendlyAuthError } from "@/lib/authErrors";
import { useAuth } from "@/lib/auth";
import { setToken } from "@/lib/token";

export default function RegisterPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register(email, password);
      // No mailer wired in v1 (PLAN.md §9 Phase 4) — verification tokens are
      // logged server-side, not emailed, so log the user straight in rather
      // than stranding them on an "check your email" screen that never works.
      const { access_token } = await login(email, password);
      setToken(access_token);
      await refresh();
      router.push("/account");
    } catch (err) {
      setError(err instanceof ApiError ? friendlyAuthError(err.message) : "Registration failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Register</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          required
          className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm focus:border-neutral-600 focus:outline-none"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          required
          minLength={8}
          className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm focus:border-neutral-600 focus:outline-none"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {submitting ? "Creating account…" : "Register"}
        </button>
      </form>
      <p className="text-sm text-neutral-500">
        Already have an account?{" "}
        <Link href="/login" className="text-neutral-300 hover:text-white">
          Log in
        </Link>
      </p>
    </main>
  );
}
