import Link from "next/link";

export default function Home() {
  return (
    <main className="bg-bg-secondary h-screen snap-y snap-mandatory">
      {" "}
      <section className="flex h-svh snap-start flex-col items-center justify-center gap-6">
        <p className="text-accent-main font-mono text-xs tracking-widest uppercase">
          ecosystem — initialized
        </p>
        <h1 className="text-center text-5xl font-light tracking-tight md:text-7xl">
          Digital Terrarium
        </h1>
        <p className="max-w-md text-center text-sm leading-relaxed opacity-60">
          A living ecosystem of autonomous AI entities. Observe, interact, and
          evolve.
        </p>
        <Link
          href="/habitat"
          className="bg-accent-main mt-4 px-6 py-3 font-mono text-xs tracking-widest text-white uppercase"
        >
          Enter →
        </Link>
      </section>
      <section className="bg-accent-soft flex h-svh snap-start flex-col items-center justify-center gap-6">
        {/* second section */}
      </section>
      <section className="flex h-svh snap-start flex-col items-center justify-center gap-6">
        {/* third section */}
      </section>
    </main>
  );
}
