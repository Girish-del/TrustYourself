// OpenAI client — cloud reasoning for Beat 2.
//
// CRITICAL: This module only ever sees the *tokenized* prompt (placeholders
// like <SECRET_001>). The cloud-audit pane in the UI pulls from the same
// strings sent to this function — judges verify with their own eyes that no
// raw secret crossed the boundary (Decision 1).

import OpenAI from "openai";

const MODEL = process.env.OPENAI_MODEL || "gpt-4o-mini";

/** Cap verbosity: shorter answers, no unsolicited “security 101” essays. */
const STRICT_SYSTEM_PROMPT = [
  "You run inside a privacy demo. The user message is TOKENIZED: placeholders like <SECRET_001>, <PII_001>, <HOST_001>, <BLOB_001> stand in for redacted spans.",
  "Rules:",
  "(1) Copy every placeholder exactly as written if you mention those spans.",
  "(2) Answer ONLY what the user is asking. Do NOT add generic security lectures, compliance preaching, or long best-practice essays unless they explicitly request that.",
  "(3) Default to brevity: tight bullets or a short paragraph. Expand only if the user clearly wants depth.",
  "(4) For code or config snippets, focus on structure, intent, and concrete next steps — not filler.",
].join(" ");

function buildCloudUserMessage(tokenizedPrompt) {
  return [
    "Instructions: Respond briefly and directly to the content below.",
    "",
    "Tokenized user content:",
    tokenizedPrompt,
  ].join("\n");
}

function maxTokens() {
  const raw = parseInt(process.env.OPENAI_MAX_TOKENS || "512", 10);
  if (Number.isNaN(raw)) return 512;
  return Math.min(4096, Math.max(64, raw));
}

function cloudTemperature() {
  const raw = parseFloat(process.env.OPENAI_CLOUD_TEMPERATURE || "0.15");
  if (Number.isNaN(raw)) return 0.15;
  return Math.min(2, Math.max(0, raw));
}

let _client = null;
function client() {
  if (!_client) {
    if (!process.env.OPENAI_API_KEY) {
      throw new Error("OPENAI_API_KEY missing — set it in .env");
    }
    _client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  }
  return _client;
}

/**
 * Async generator of delta text chunks for the reassembler.
 *
 * @param {string} tokenizedPrompt
 */
export async function* cloudStream(tokenizedPrompt) {
  const stream = await client().chat.completions.create({
    model: MODEL,
    messages: [
      { role: "system", content: STRICT_SYSTEM_PROMPT },
      { role: "user", content: buildCloudUserMessage(tokenizedPrompt) },
    ],
    temperature: cloudTemperature(),
    max_tokens: maxTokens(),
    stream: true,
  });
  for await (const chunk of stream) {
    const delta = chunk.choices?.[0]?.delta?.content || "";
    if (delta) yield delta;
  }
}

/**
 * Callback-style API (optional callers / tests).
 *
 * @param {string} tokenizedPrompt
 * @param {(evt:{type:'token'|'done'|'error', text?:string, elapsedMs?:number, error?:string}) => void} onEvent
 */
export async function streamCompletion(tokenizedPrompt, onEvent) {
  const started = performance.now();
  let buffer = "";
  try {
    for await (const text of cloudStream(tokenizedPrompt)) {
      buffer += text;
      onEvent({ type: "token", text });
    }
    const elapsedMs = Math.round(performance.now() - started);
    onEvent({ type: "done", elapsedMs });
    return { text: buffer, elapsedMs, model: MODEL };
  } catch (err) {
    const message = err?.message ?? String(err);
    onEvent({ type: "error", error: message });
    return {
      text: buffer,
      elapsedMs: Math.round(performance.now() - started),
      model: MODEL,
      error: message,
    };
  }
}

export function modelName() {
  return MODEL;
}
