"use client";
import { useState } from "react";
import Link from "next/link";
import { loginUser } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const router = useRouter();
  async function handleLogin() {
    if (identifier == null || password == null) {
      return;
    }
    const { data, error } = await loginUser(identifier, password);
    if (error) {
      console.log("Error:", error.message);
      return;
    }

    console.log("Account created!", data);
    router.push("/habitat");
    // redirect to login or habitat here
  }
  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="flex w-full max-w-sm flex-col gap-4">
        <p className="text-accent-main font-mono text-xs tracking-widest uppercase">
          observer access
        </p>
        <h1 className="text-4xl font-light tracking-tight">Welcome back.</h1>
        <p className="mb-4 text-sm leading-relaxed opacity-60">
          Sign in to interact with the ecosystem.
        </p>

        <input
          type="text"
          placeholder="Email or Username"
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          className="border-accent-main border-b bg-transparent px-1 py-3 text-sm outline-none placeholder:opacity-40"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="border-accent-main border-b bg-transparent px-1 py-3 text-sm outline-none placeholder:opacity-40"
        />

        <button
          onClick={handleLogin}
          className="bg-accent-main mt-4 px-6 py-3 font-mono text-xs tracking-widest text-white uppercase"
        >
          Enter →
        </button>

        <Link
          href="/register"
          className="mt-2 text-center font-mono text-xs tracking-widest uppercase opacity-40"
        >
          No account? Register
        </Link>
      </div>
    </main>
  );
}
