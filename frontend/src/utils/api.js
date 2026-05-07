export const BACKEND_URL =
  import.meta.env.VITE_BACKEND_URL ||
  "https://bismillah-super-trading-terminal-production.up.railway.app";

console.log("[API] BACKEND_URL:", BACKEND_URL);

export async function apiFetch(path, options = {}) {
  const url = `${BACKEND_URL}${path}`;
  console.log("[API] Fetching:", url);

  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`HTTP ${res.status}: ${errText}`);
  }

  return res.json();
}

export async function runScreener(mode = "swing") {
  return apiFetch("/api/screener/run", {
    method: "POST",
    body: JSON.stringify({ mode: mode.toLowerCase() }),
  });
}

export async function checkHealth() {
  return apiFetch("/health");
}
