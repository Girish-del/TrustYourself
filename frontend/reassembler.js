/**
 * Reassembler (Decision 2 / M2 mechanism).
 *
 * Pipeline:
 *   1. Call backend /redact to tokenize sensitive content
 *   2. Launch cloud stream (gpt-4o-mini) with TOKENIZED prompt
 *   3. Launch local stream (Phi-3 via backend) with FULL prompt (stays in TEE in v2)
 *   4. Merge: cloud handles structure; local has secret-aware context
 *   5. Sign every event into the audit log
 *
 * The cloud-audit + local-audit panes (Decision 1, 7) make the trust property visible:
 * judges can see exactly what crossed the boundary to OpenAI.
 */

import crypto from 'crypto';
import { redact, localInferStream, signEvent, backendHealth } from './backend_client.js';
import { cloudStream } from './cloud_llm.js';

const SENSITIVE_CATEGORIES = new Set(['secret', 'high_entropy']);

export async function runChat(prompt, onEvent) {
  // 1. Redact
  const redacted = await redact(prompt);
  for (const ev of redacted.events) {
    signEvent('redaction', ev).catch(() => {});
    const row = { type: 'redaction', ...ev };
    // Plaintext only for local UI + reassembly — never included in signed payload (API omits original).
    if (SENSITIVE_CATEGORIES.has(ev.category)) {
      row.sensitive_plaintext = prompt.slice(ev.start, ev.end);
    }
    onEvent(row);
  }

  // Audit panes (Decision 1 + Decision 2)
  onEvent({
    type: 'audit',
    source: 'cloud',
    bytes: JSON.stringify(
      {
        model: process.env.OPENAI_MODEL || 'gpt-4o-mini',
        prompt: redacted.redacted_text,
      },
      null,
      2,
    ),
  });
  onEvent({
    type: 'audit',
    source: 'local',
    bytes: JSON.stringify(
      {
        model: process.env.OLLAMA_MODEL || 'phi3:mini',
        prompt,
        note: 'In production, this prompt never leaves the TEE.',
      },
      null,
      2,
    ),
  });

  // 2 + 3. Launch both streams in parallel
  const cloudPromise = collectStream(cloudStream(redacted.redacted_text), 'cloud', onEvent);
  const localPromise = collectStream(localInferStream(prompt), 'local', onEvent);

  const [cloudResponse, localResponse] = await Promise.all([
    cloudPromise.catch((e) => `[cloud error: ${e.message || e}]`),
    localPromise.catch((e) => `[local error: ${e.message || e}]`),
  ]);

  // 4. Reassemble (Decision 5 try/catch fallback)
  let finalOutput;
  try {
    finalOutput = rehydrate(cloudResponse, redacted.events, prompt);
  } catch (e) {
    finalOutput =
      `[reassembler fallback — would happen inside TEE in production]\n\n` +
      `--- cloud (structure) ---\n${cloudResponse}\n\n` +
      `--- local (secret-aware) ---\n${localResponse}`;
  }

  // 5. Sign the completion event
  signEvent('completion', {
    cloud_hash: hashOf(cloudResponse),
    local_hash: hashOf(localResponse),
  }).catch(() => {});

  onEvent({ type: 'final', text: finalOutput });
}

async function collectStream(streamIter, source, onEvent) {
  let buffer = '';
  for await (const token of streamIter) {
    buffer += token;
    onEvent({ type: 'stream', source, token });
  }
  return buffer;
}

/**
 * Substitute placeholders in cloud's response with original values from redaction events.
 * In v2 production this happens inside the TEE so original values never re-enter user-facing
 * memory in the orchestrator process.
 */
function rehydrate(text, events, fullPrompt) {
  let out = text;
  for (const ev of events) {
    const token = ev.replacement || ev.placeholder;
    if (!token) continue;
    const original = fullPrompt.slice(ev.start, ev.end);
    out = out.split(token).join(original);
  }
  return out;
}

function hashOf(s) {
  return crypto.createHash('sha256').update(s).digest('hex').slice(0, 16);
}

export async function aggregateHealth() {
  const backend = await backendHealth();
  return {
    status: backend.status === 'ok' ? 'ok' : 'degraded',
    services: {
      backend,
      frontend: { status: 'ok' },
    },
  };
}
