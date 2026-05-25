"use client";
import { useEffect, useState, createContext, useContext } from "react";
import Lenis from "lenis";
import supabase from "@/lib/supabase";
import { Session } from "@supabase/supabase-js";
import { getMyProfile } from "@/lib/auth";

interface AuthContextType {
  session: Session | null;
  isAdmin: boolean;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType>({
  session: null,
  isAdmin: false,
  loading: true,
});

export function useAuth() {
  return useContext(AuthContext);
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  async function fetchProfile(userId: string) {
    const { data } = await getMyProfile();
    setIsAdmin(data?.is_admin ?? false);
  }
  useEffect(() => {
    const nav = document.getElementById("main-nav");
    if (nav) {
      document.documentElement.style.setProperty(
        "--nav-height",
        `${nav.offsetHeight}px`,
      );
    }
  }, []);
  useEffect(() => {
    // Lenis smooth scrolling
    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      prevent: (node) => node.closest("[data-lenis-prevent]") !== null,
    });
    function raf(time: number) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);

    // check existing session on load
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      if (session) fetchProfile(session.user.id);
      setLoading(false); // ← done checking
    });

    // listen for auth changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event, session) => {
      setSession(session);
      if (session) {
        fetchProfile(session.user.id);
      } else {
        setIsAdmin(false);
      }
    });

    return () => {
      lenis.destroy();
      subscription.unsubscribe();
    };
  }, []);

  return (
    <AuthContext.Provider value={{ session, isAdmin, loading }}>
      {children}
    </AuthContext.Provider>
  );
}
