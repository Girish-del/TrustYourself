/**
 * HTTP client for the Python FastAPI backend (redact, local infer, signing).
 */

const PY_PORT = process.env.PY_PORT || "8001";
const BACKEND = `http://127.0.0.1:${PY_PORT}`;

export async function redact(text) {
  const r = await fetch(`${BACKEND}/redact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`redact ${r.status}: ${body}`);
  }
  return r.json();
}

export async function* localInferStream(prompt) {
  const r = await fetch(`${BACKEND}/local-infer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!r.ok) {
    throw new Error(`local-infer ${r.status}: ${await r.text()}`);
  }
  const reader = r.body?.getReader();
  if (!reader) throw new Error("local-infer: no response body");
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const block of parts) {
      for (const line of block.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (raw === "[DONE]") continue;
        try {
          const j = JSON.parse(raw);
          if (j.error) throw new Error(j.error);
          if (j.token != null && j.token !== "") yield j.token;
        } catch (e) {
          if (e instanceof SyntaxError) continue;
          throw e;
        }
      }
    }
  }
}

export async function signEvent(eventType, payload) {
  const r = await fetch(`${BACKEND}/sign-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: eventType, payload }),
  });
  if (!r.ok) {
    throw new Error(`sign-event ${r.status}: ${await r.text()}`);
  }
  return r.json();
}

export async function backendHealth() {
  try {
    const r = await fetch(`${BACKEND}/health`);
    if (!r.ok) return { status: "error", detail: String(r.status) };
    return await r.json();
  } catch (e) {
    return { status: "error", detail: String(e?.message || e) };
  }
}
