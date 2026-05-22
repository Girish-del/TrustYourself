/**
 * TrustYourself — UI wired to index.html (Beat 1 / 2 / 3 layout).
 * Streams from POST /api/chat (SSE JSON lines: redaction | stream | audit | final | error).
 */

const MAX_INPUT_BYTES = 10240;

const inputEl = document.getElementById('input');
const sizeHint = document.getElementById('size-hint');
const runBtn = document.getElementById('run-btn');
const redactionList = document.getElementById('redaction-list');

const cloudStream = document.getElementById('cloud-stream');
const cloudLatency = document.getElementById('cloud-latency');
const cloudModelEl = document.getElementById('cloud-model');
const localStream = document.getElementById('local-stream');
const localLatency = document.getElementById('local-latency');
const localModelEl = document.getElementById('local-model');

const outputStream = document.getElementById('output-stream');
const reassembleDecisions = document.getElementById('reassemble-decisions');

const rSession = document.getElementById('r-session');
const rEvents = document.getElementById('r-events');
const rRoot = document.getElementById('r-root');
const rVk = document.getElementById('r-vk');

const cloudAuditNote = document.getElementById('cloud-audit-note');
const cloudAuditBytes = document.getElementById('cloud-audit-bytes');
const localAuditNote = document.getElementById('local-audit-note');
const localAuditBytes = document.getElementById('local-audit-bytes');

const dotNode = document.querySelector('.dot-node');
const dotPy = document.querySelector('.dot-py');
const dotOllama = document.querySelector('.dot-ollama');
const healthLabel = document.getElementById('health-label');

let examples = {};

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function updateSize() {
  const n = new Blob([inputEl.value]).size;
  sizeHint.textContent = `${n.toLocaleString()} / ${MAX_INPUT_BYTES.toLocaleString()} B`;
  sizeHint.classList.toggle('over', n > MAX_INPUT_BYTES);
  runBtn.disabled = n === 0 || n > MAX_INPUT_BYTES;
}

async function loadExamples() {
  try {
    const r = await fetch('/api/examples');
    if (r.ok) examples = await r.json();
  } catch (e) {
    console.warn('examples:', e);
  }
}

document.querySelectorAll('[data-example]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const id = btn.dataset.example;
    inputEl.value = examples[id] || '';
    updateSize();
    inputEl.focus();
  });
});

inputEl.addEventListener('input', updateSize);
updateSize();

function setDot(el, ok) {
  if (!el) return;
  el.dataset.state = ok ? 'ok' : 'bad';
}

async function pollHealth() {
  try {
    const r = await fetch('/api/health');
    const j = await r.json();
    const backend = j.services?.backend || {};
    const pyOk = backend.status === 'ok' && backend.service === 'backend';
    const ollamaOk = backend.ollama?.ok === true;
    setDot(dotNode, true);
    setDot(dotPy, pyOk);
    setDot(dotOllama, ollamaOk);
    if (pyOk && ollamaOk) {
      healthLabel.textContent = `node · py · ${backend.ollama?.model || 'ollama'} ✓`;
    } else if (pyOk && !ollamaOk) {
      healthLabel.textContent = 'ollama offline — local stream may fail';
    } else {
      healthLabel.textContent = 'backend unreachable';
    }
    if (j.services?.backend && backend.service === 'backend') {
      const m = backend.ollama?.model;
      if (m) localModelEl.textContent = m;
    }
  } catch {
    setDot(dotNode, false);
    setDot(dotPy, false);
    setDot(dotOllama, false);
    healthLabel.textContent = 'health check failed';
  }
}

runBtn.addEventListener('click', runPipeline);

async function runPipeline() {
  const prompt = inputEl.value.trim();
  if (!prompt) return;

  redactionList.innerHTML =
    '<p class="empty-hint">Processing…</p>';
  cloudStream.textContent = '';
  localStream.textContent = '';
  outputStream.innerHTML = '<span class="muted">Running…</span>';
  reassembleDecisions.innerHTML = '';
  cloudLatency.textContent = '…';
  cloudLatency.classList.add('pending');
  localLatency.textContent = '…';
  localLatency.classList.add('pending');
  rSession.textContent = '—';
  rEvents.textContent = '0';
  rRoot.textContent = '—';
  rVk.textContent = '—';
  cloudAuditNote.textContent = '';
  cloudAuditBytes.textContent = '';
  localAuditNote.textContent = '';
  localAuditBytes.textContent = '';

  let cloudStart = 0;
  let localStart = 0;
  let cloudFirst = null;
  let localFirst = null;

  runBtn.disabled = true;
  runBtn.textContent = 'Running…';

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });

    if (!resp.ok) {
      const t = await resp.text();
      outputStream.innerHTML = `<span class="muted">Error: ${escapeHtml(t.slice(0, 400))}</span>`;
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let sawRedaction = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const blocks = buf.split('\n\n');
      buf = blocks.pop() || '';
      for (const block of blocks) {
        const line = block.split('\n').find((l) => l.startsWith('data: '));
        if (!line) continue;
        let ev;
        try {
          ev = JSON.parse(line.slice(6));
        } catch {
          continue;
        }
        switch (ev.type) {
          case 'redaction':
            if (!sawRedaction) {
              redactionList.innerHTML = '';
              sawRedaction = true;
            }
            appendRedactionRow(ev);
            break;
          case 'stream':
            if (ev.source === 'cloud') {
              if (!cloudStart) cloudStart = performance.now();
              cloudStream.textContent += ev.token || '';
              cloudStream.scrollTop = cloudStream.scrollHeight;
              if (cloudFirst === null) cloudFirst = performance.now();
              cloudLatency.textContent = `${Math.round(performance.now() - cloudStart)} ms`;
              cloudLatency.classList.remove('pending');
            } else if (ev.source === 'local') {
              if (!localStart) localStart = performance.now();
              localStream.textContent += ev.token || '';
              localStream.scrollTop = localStream.scrollHeight;
              if (localFirst === null) localFirst = performance.now();
              localLatency.textContent = `${Math.round(performance.now() - localStart)} ms`;
              localLatency.classList.remove('pending');
            }
            break;
          case 'audit':
            if (ev.source === 'cloud') {
              cloudAuditNote.textContent = 'Exact payload boundary (tokenized).';
              cloudAuditBytes.textContent = ev.bytes || '';
            } else if (ev.source === 'local') {
              localAuditNote.textContent = 'Full prompt to local model.';
              localAuditBytes.textContent = ev.bytes || '';
            }
            break;
          case 'final':
            outputStream.textContent = ev.text || '—';
            break;
          case 'error':
            outputStream.innerHTML = `<span class="muted">${escapeHtml(ev.error || 'error')}</span>`;
            break;
          default:
            break;
        }
      }
    }

    if (!sawRedaction) {
      redactionList.innerHTML =
        '<p class="empty-hint">No redaction rules fired for this input.</p>';
    }

    await refreshReceipt();
  } catch (err) {
    outputStream.innerHTML = `<span class="muted">${escapeHtml(err.message)}</span>`;
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = 'Run pipeline ▶';
    updateSize();
  }
}

function appendRedactionRow(ev) {
  const row = document.createElement('div');
  const cat = (ev.category || 'pii').toLowerCase().replace(/\s/g, '_');
  row.className = `redaction-row cat-${cat}`;
  const rule = escapeHtml(ev.rule || 'rule');
  const ph = escapeHtml(ev.placeholder || ev.replacement || '—');
  row.innerHTML = `
    <div class="row-top">
      <span class="ph">${ph}</span>
      <span class="rule" title="Rule">${rule}</span>
    </div>
    <div class="span-info">offset ${ev.start ?? '—'}–${ev.end ?? '—'} · ${ev.category || ''}</div>`;
  redactionList.appendChild(row);
}

async function refreshReceipt() {
  try {
    const r = await fetch('/api/audit-summary');
    if (!r.ok) return;
    const s = await r.json();
    rSession.textContent = s.session_id || '—';
    rEvents.textContent = String(s.event_count ?? 0);
    rRoot.textContent = s.merkle_root || '—';
    rVk.textContent = s.verify_key || '—';
  } catch {
    /* ignore */
  }
}

loadExamples();
pollHealth();
setInterval(pollHealth, 5000);
