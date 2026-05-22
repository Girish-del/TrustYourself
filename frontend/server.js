/**
 * TrustYourself frontend service (Node, Express, port 3000).
 *
 * Responsibilities:
 *   - Serve the static UI from public/
 *   - Orchestrate the redact -> split -> infer -> reassemble flow (M2 mechanism)
 *   - Talk to the Python backend (localhost:8001) for redaction, local infer, signing
 *   - Talk to OpenAI directly for cloud infer
 */

import express from 'express';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';
import { promises as fs } from 'fs';
import { runChat, aggregateHealth } from './reassembler.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '..', '.env') });

const app = express();
const PORT = process.env.FRONTEND_PORT || process.env.NODE_PORT || 3000;
const INPUT_LIMIT = parseInt(process.env.INPUT_LIMIT_BYTES || '10240', 10);
const PY_PORT = process.env.PY_PORT || '8001';
const PY_BASE = `http://127.0.0.1:${PY_PORT}`;

async function proxyJson(method, pathname, body) {
  const url = `${PY_BASE}${pathname}`;
  const init = { method, headers: { accept: 'application/json' } };
  if (body !== undefined) {
    init.headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const r = await fetch(url, init);
  const text = await r.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  return { status: r.status, data };
}

app.use(express.json({ limit: '64kb' }));
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/health', async (req, res) => {
  try {
    res.json(await aggregateHealth());
  } catch (e) {
    res.status(500).json({ status: 'error', error: String(e) });
  }
});

app.get('/api/examples', async (req, res) => {
  try {
    const data = await fs.readFile(
      path.join(__dirname, '..', 'eval', 'pre_loaded_examples.json'),
      'utf8',
    );
    const examples = JSON.parse(data);
    const map = Object.fromEntries(examples.map((e) => [e.id, e.prompt]));
    // Short keys for buttons (data-example="auth" etc.)
    if (map.auth_handler) map.auth = map.auth_handler;
    if (map.medical_query) map.medical = map.medical_query;
    if (map.infra_config) map.infra = map.infra_config;
    res.json(map);
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get('/api/audit-log', async (req, res) => {
  try {
    const { status, data } = await proxyJson('GET', '/audit-log');
    res.status(status).json(data);
  } catch (e) {
    res.status(502).json({ error: String(e) });
  }
});

app.get('/api/audit-summary', async (req, res) => {
  try {
    const { status, data } = await proxyJson('GET', '/audit-summary');
    res.status(status).json(data);
  } catch (e) {
    res.status(502).json({ error: String(e) });
  }
});

app.post('/api/verify', async (req, res) => {
  try {
    const { status, data } = await proxyJson('POST', '/verify-log', req.body || {});
    res.status(status).json(data);
  } catch (e) {
    res.status(502).json({ error: String(e) });
  }
});

app.post('/api/chat', async (req, res) => {
  const { prompt } = req.body;
  if (!prompt || typeof prompt !== 'string') {
    return res.status(400).json({ error: 'prompt required (string)' });
  }
  if (Buffer.byteLength(prompt, 'utf8') > INPUT_LIMIT) {
    return res.status(413).json({ error: `prompt > ${INPUT_LIMIT} bytes` });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  try {
    await runChat(prompt, (event) => {
      res.write(`data: ${JSON.stringify(event)}\n\n`);
    });
  } catch (e) {
    res.write(`data: ${JSON.stringify({ type: 'error', error: String(e) })}\n\n`);
  }
  res.end();
});

app.listen(PORT, () => {
  console.log(`[node] TrustYourself frontend listening on http://localhost:${PORT}`);
  console.log(`[node] Python backend expected at ${PY_BASE}`);
});
