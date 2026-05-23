"use client";
import Link from "next/link";
import { useState } from "react";
import { registerUser } from "@/lib/auth";

import supabase from "@/lib/supabase";
import { useRouter } from "next/navigation";

export default function Register() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const router = useRouter();

  async function handleRegister() {
    if (!username || !email || !password || !confirmPassword) {
      console.log("All fields are required!");
      return;
    }

    if (password !== confirmPassword) {
      console.log("Passwords do not match!");
      return;
    }

    if (password.length < 8) {
      console.log("Password must be at least 8 characters!");
      return;
    }

    const { data, error } = await registerUser(email, password, username);

    if (error) {
      console.log("Error:", error.message);
      return;
    }

    console.log("Account created!", data);
    router.push("/habitat");
  }
  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="flex w-full max-w-sm flex-col gap-4">
        <p className="text-accent-main font-mono text-xs tracking-widest uppercase">
          new observer
        </p>
        <h1 className="text-4xl font-light tracking-tight">
          Join the ecosystem.
        </h1>
        <p className="mb-4 text-sm leading-relaxed opacity-60">
          Create an account to interact with the habitat.
        </p>

        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="border-accent-main border-b bg-transparent px-1 py-3 text-sm outline-none placeholder:opacity-40"
        />
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="border-accent-main border-b bg-transparent px-1 py-3 text-sm outline-none placeholder:opacity-40"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="border-accent-main border-b bg-transparent px-1 py-3 text-sm outline-none placeholder:opacity-40"
        />
        <input
          type="password"
          placeholder="Confirm Password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          className="border-accent-main border-b bg-transparent px-1 py-3 text-sm outline-none placeholder:opacity-40"
        />

        <button
          onClick={handleRegister}
          className="bg-accent-main mt-4 px-6 py-3 font-mono text-xs tracking-widest text-white uppercase"
        >
          Create Account →
        </button>

        <Link
          href="/login"
          className="mt-2 text-center font-mono text-xs tracking-widest uppercase opacity-40"
        >
          Already have an account? Login
        </Link>
      </div>
    </main>
  );
}
