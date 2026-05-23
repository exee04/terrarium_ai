"use client";
import Link from "next/link";
import { useAuth } from "@/app/providers";
import { usePathname } from "next/navigation";
import { useState } from "react";
import supabase from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

export default function Nav() {
  const { session, isAdmin, loading } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const router = useRouter();
  if (loading) return null;
  async function handleLogout() {
    await supabase.auth.signOut();
    setMenuOpen(false);
    router.push("/login");
  }
  const navRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (navRef.current) {
      document.documentElement.style.setProperty(
        "--nav-height",
        `${navRef.current.offsetHeight}px`,
      );
    }
  }, [loading]);

  return (
    <nav
      ref={navRef}
      id="main-nav"
      className="fixed top-0 right-0 left-0 z-50 flex justify-between px-8 py-6"
    >
      {" "}
      {/* Left — logo */}
      <Link href="/" className="font-mono text-xs tracking-widest uppercase">
        Digital Terrarium
      </Link>
      {/* Right */}
      <div className="relative">
        {session ? (
          <>
            {/* Username button */}
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="font-mono text-xs tracking-widest uppercase opacity-60 hover:opacity-100"
            >
              {session.user.user_metadata.username}
              {isAdmin && " · ADMIN"}
            </button>

            {/* Dropdown modal */}
            {menuOpen && (
              <div className="bg-bg-primary border-accent-soft absolute top-8 right-0 flex min-w-40 flex-col gap-3 border p-4">
                <p className="font-mono text-xs tracking-widest uppercase">
                  {session.user.user_metadata.username}
                </p>
                {isAdmin && (
                  <p className="text-accent-main font-mono text-xs tracking-widest uppercase">
                    Admin
                  </p>
                )}
                <div className="border-accent-soft border-t" />
                <button
                  onClick={handleLogout}
                  className="text-left font-mono text-xs tracking-widest uppercase opacity-60 hover:opacity-100"
                >
                  Logout →
                </button>
              </div>
            )}
          </>
        ) : (
          pathname !== "/login" && (
            <Link
              href="/login"
              className="font-mono text-xs tracking-widest uppercase opacity-60 hover:opacity-100"
            >
              Login
            </Link>
          )
        )}
      </div>
    </nav>
  );
}
