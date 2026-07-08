"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function NavBar() {
  const { user, loading, logout } = useAuth();

  return (
    <nav className="flex items-center justify-between border-b border-neutral-800 px-8 py-4">
      <Link href="/" className="font-semibold">
        IngressFlow
      </Link>
      <div className="flex items-center gap-4 text-sm">
        {loading ? null : user ? (
          <>
            <span className="text-neutral-500">
              {user.email} <span className="uppercase text-neutral-600">({user.role})</span>
            </span>
            <Link href="/account" className="text-neutral-300 hover:text-white">
              Account
            </Link>
            {user.is_superuser && (
              <Link href="/admin" className="text-neutral-300 hover:text-white">
                Admin
              </Link>
            )}
            <button onClick={logout} className="text-neutral-300 hover:text-white">
              Log out
            </button>
          </>
        ) : (
          <>
            <Link href="/login" className="text-neutral-300 hover:text-white">
              Log in
            </Link>
            <Link href="/register" className="text-neutral-300 hover:text-white">
              Register
            </Link>
          </>
        )}
      </div>
    </nav>
  );
}
