// Verifier page — Beat 3.
// Pastes a Merkle root, fetches the audit log, asks the Python service to
// verify every signature + recompute the root, prints a green checkmark.

const $ = (sel) => document.querySelector(sel);
const rootInput = $("#root-input");
const verifyBtn = $("#verify-btn");
const autofillBtn = $("#autofill-btn");
const result = $("#v-result");
const icon = $("#v-icon");
const headline = $("#v-headline");
const stats = $("#v-stats");
const tableBody = $("#events-table tbody");
const entryCount = $("#entry-count");

verifyBtn.addEventListener("click", verify);
autofillBtn.addEventListener("click", autofill);
rootInput.addEventListener("keydown", (e) => { if (e.key === "Enter") verify(); });

async function autofill() {
  try {
    const r = await fetch("/api/audit-log");
    const log = await r.json();
    rootInput.value = log.merkle_root || "";
    renderEntries(log.events || []);
    setResult("idle", "Loaded current session log. Click Verify ✓.", `${log.events?.length || 0} events`);
  } catch (err) {
    setResult("bad", "Couldn't fetch session log.", err.message);
  }
}

async function verify() {
  const root = rootInput.value.trim();
  if (!/^[0-9a-f]{64}$/i.test(root)) {
    setResult("bad", "Invalid Merkle root.", "Expected 64 hex chars.");
    return;
  }

  setResult("idle", "Verifying…", "");

  try {
    // 1) Fetch the full log from the orchestrator (proxied to Python).
    const logResp = await fetch("/api/audit-log");
    const log = await logResp.json();
    renderEntries(log.events || []);

    // 2) Ask Python to recompute the Merkle root + verify every signature.
    const verifyResp = await fetch("/api/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        envelopes: log.events || [],
        expected_root: root,
      }),
    });
    const v = await verifyResp.json();

    const okSig = v.bad_signatures?.length === 0;
    const okRoot = v.match;
    const okAll = okSig && okRoot;

    if (okAll) {
      setResult(
        "ok",
        "✓ Receipt verified",
        `${v.events} events · all ed25519 signatures valid · Merkle root matches`
      );
    } else {
      const reasons = [];
      if (!okSig) reasons.push(`${v.bad_signatures.length} bad signature(s) at index ${v.bad_signatures.join(", ")}`);
      if (!okRoot) reasons.push(`Merkle root mismatch (recomputed=${(v.recomputed_root || "").slice(0, 12)}…)`);
      setResult("bad", "✗ Verification failed", reasons.join(" · "));
      // Mark bad rows.
      if (v.bad_signatures?.length) {
        const rows = tableBody.querySelectorAll("tr");
        v.bad_signatures.forEach((idx) => rows[idx]?.classList.add("bad"));
      }
    }
  } catch (err) {
    setResult("bad", "Verification request failed.", err.message);
  }
}

function setResult(state, headlineText, statsText) {
  result.classList.remove("ok", "bad");
  if (state === "ok") {
    result.classList.add("ok");
    icon.textContent = "✓"; icon.className = "v-icon ok";
  } else if (state === "bad") {
    result.classList.add("bad");
    icon.textContent = "✗"; icon.className = "v-icon bad";
  } else {
    icon.textContent = "◐"; icon.className = "v-icon";
  }
  headline.textContent = headlineText;
  stats.textContent = statsText;
}

function renderEntries(events) {
  tableBody.innerHTML = "";
  entryCount.textContent = `${events.length} entries`;
  events.forEach((env, i) => {
    const tr = document.createElement("tr");
    const ts = env.payload?.ts_ms ? new Date(env.payload.ts_ms).toISOString() : "—";
    tr.innerHTML = `
      <td>${i}</td>
      <td class="event-type">${escapeHtml(env.payload?.event_type || "?")}</td>
      <td>${escapeHtml(ts)}</td>
      <td class="hash" title="${escapeHtml(env.payload_hash || "")}">${escapeHtml((env.payload_hash || "").slice(0, 16))}…</td>
      <td title="${escapeHtml(env.signature || "")}">${escapeHtml((env.signature || "").slice(0, 16))}…</td>
    `;
    tableBody.appendChild(tr);
  });
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
