"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

const ADMIN_LINKS = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/settings", label: "Settings" },
  { href: "/admin/credentials", label: "Credentials" },
  { href: "/admin/cms", label: "Legal pages" },
  { href: "/admin/audit", label: "Audit log" },
  { href: "/admin/platforms", label: "Platform health" },
  { href: "/admin/proxy-nodes", label: "Residential nodes" },
];

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && (!user || !user.is_superuser)) router.push("/");
  }, [loading, user, router]);

  if (loading || !user || !user.is_superuser) {
    return <main className="p-8 text-neutral-400">Loading…</main>;
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl gap-8 p-8">
      <nav className="flex w-40 shrink-0 flex-col gap-1 text-sm">
        {ADMIN_LINKS.map((l) => (
          <Link key={l.href} href={l.href} className="rounded-lg px-3 py-2 text-neutral-300 hover:bg-neutral-900 hover:text-white">
            {l.label}
          </Link>
        ))}
      </nav>
      <div className="flex-1">{children}</div>
    </div>
  );
}
