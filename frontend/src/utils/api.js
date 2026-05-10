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

export async function analyzeStock(ticker, mode = "swing") {
  return apiFetch(`/api/analytic/analyze`, {
    method: "POST",
    body: JSON.stringify({ ticker, mode: mode.toLowerCase() }),
  });
}

export async function getMonitoring() {
  return apiFetch("/api/monitoring/status", {
    method: "POST",
    body: JSON.stringify({ ticker }),
  });
}

export async function getMonitoringList() {
  return apiFetch("/api/monitoring/active", { method: "GET" });
}

export async function startMonitoring(payload) {
  return apiFetch("/api/monitoring/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function removeMonitoring(ticker) {
  return apiFetch("/api/monitoring/remove", {
    method: "POST",
    body: JSON.stringify({ ticker }),
  });
}

export async function getScalpingData(ticker) {
  return apiFetch(`/api/scalping/data/${ticker}`, { method: "GET" });
}

export function getWsUrl() {
  return BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://");
}

export async function checkMonitoring(payload) {
  return apiFetch("/api/monitoring/check", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
