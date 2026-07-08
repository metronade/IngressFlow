async function getHealth() {
  const base = process.env.INTERNAL_API_URL ?? "http://api:8000";
  try {
    const res = await fetch(`${base}/api/health`, { cache: "no-store" });
    return { reachable: res.ok, body: await res.json() };
  } catch (err) {
    return { reachable: false, body: { error: String(err) } };
  }
}

export default async function Home() {
  const health = await getHealth();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-2xl font-semibold">IngressFlow</h1>
      <p className="text-neutral-400">Phase A — foundations round trip: web → api → db → redis</p>
      <pre
        className={`rounded-lg border px-4 py-3 text-sm ${
          health.reachable ? "border-green-700 bg-green-950" : "border-red-700 bg-red-950"
        }`}
      >
        {JSON.stringify(health.body, null, 2)}
      </pre>
    </main>
  );
}
