/* WATCH OOZE — frontend logic */

const $ = (sel) => document.querySelector(sel);

// ───────── formatters ─────────

function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  if (typeof n === 'string') return n;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtSol(s, opts = {}) {
  if (s === null || s === undefined) return '—';
  const compact = opts.compact ?? false;
  if (compact) {
    if (s >= 1e6) return (s / 1e6).toFixed(2) + 'M';
    if (s >= 1e3) return (s / 1e3).toFixed(1) + 'K';
    return s.toFixed(2);
  }
  if (s >= 1e6) return (s / 1e6).toFixed(3) + 'M';
  if (s >= 1e3) return s.toFixed(2);
  if (s < 0.001 && s > 0) return s.toFixed(9);
  return s.toFixed(4);
}

function fmtLamports(n) {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString();
}

function shortKey(k) {
  if (!k || typeof k !== 'string') return '—';
  if (k.length <= 14) return k;
  return k.slice(0, 6) + '…' + k.slice(-6);
}

function rpcHostname(url) {
  if (!url) return 'staccana';
  try { return new URL(url).host; }
  catch { return url; }
}

// ───────── render rows ─────────

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderRow(record, isOurs) {
  const tr = document.createElement('tr');
  tr.className = isOurs ? 'row-ours' : 'row-other';

  const pubkey = isOurs ? record.validator : shortKey(record.validator);
  const tagHtml = isOurs
    ? '<span class="tag tag-ours">OOZE\u2019S</span>'
    : '<span class="tag">VALIDATOR</span>';

  tr.innerHTML = `
    <td class="col-validator">
      <div class="cell-validator">
        ${tagHtml}
        <code class="cell-pubkey">${escapeHtml(pubkey)}</code>
      </div>
    </td>
    <td class="col-uptime">
      <div class="cell-num cell-num-strong">${(record.uptimePct ?? 0).toFixed(2)}%</div>
      <div class="cell-sub">${(record.uptimeBps ?? 0)} bps</div>
    </td>
    <td class="col-stake">
      <div class="cell-num cell-num-strong">${fmtSol(record.delegatedStakeSol)} ◎</div>
      <div class="cell-sub">${fmtLamports(record.delegatedStakeLamports)}</div>
    </td>
    <td class="col-votes">
      <div class="cell-num cell-num-strong">${fmtNum(record.votesCast)}</div>
      <div class="cell-sub">cast</div>
    </td>
    <td class="col-subsidy">
      <div class="cell-num cell-num-strong">${fmtSol(record.lifetimeSubsidySol)} ◎</div>
      <div class="cell-sub">${fmtLamports(record.lifetimeSubsidyLamports)}</div>
    </td>
    <td class="col-epoch">
      <div class="cell-num">${record.lastDistributionEpoch ?? '—'}</div>
      <div class="cell-sub">last paid</div>
    </td>
    <td class="col-nonce">
      <div class="cell-num">${record.lastMetricsNonce ?? '—'}</div>
      <div class="cell-sub">slot ${typeof record.lastMetricsSlot === 'number'
        ? record.lastMetricsSlot.toLocaleString()
        : '—'}</div>
    </td>
  `;

  return tr;
}

function renderAll(payload) {
  const ourPubkey = payload.ourValidator;
  const records = payload.validators || [];

  // status strip
  $('#strip-count').textContent = fmtNum(payload.registeredCount);
  $('#strip-slot').textContent = fmtNum(payload.slot);
  $('#strip-epoch').textContent = fmtNum(payload.epoch);

  const totalLamports = records.reduce((s, r) => s + (r.lifetimeSubsidyLamports || 0), 0);
  $('#strip-total').textContent = fmtSol(totalLamports / 1e9, { compact: true }) + ' ◎';

  // sync indicator
  const light = $('#sync-light');
  const label = $('#sync-label');
  light.classList.remove('err');
  label.classList.remove('err');
  label.textContent = 'SYNC';

  $('#rpc-foot').textContent = rpcHostname(payload.rpcUrl);

  const ours = records.find((r) => r.validator === ourPubkey);
  const others = records.filter((r) => r.validator !== ourPubkey);

  const tbody = $('#rows');
  tbody.innerHTML = '';

  if (records.length === 0) {
    const tr = document.createElement('tr');
    tr.className = 'empty-row';
    tr.innerHTML = '<td colspan="7">// no validators in registry</td>';
    tbody.appendChild(tr);
    return;
  }

  if (ours) {
    tbody.appendChild(renderRow(ours, true));
  }
  for (const record of others) {
    tbody.appendChild(renderRow(record, false));
  }
}

// ───────── poll ─────────

let fails = 0;

async function tick() {
  try {
    const res = await fetch('/api/validators', { cache: 'no-store' });
    if (!res.ok) throw new Error('http ' + res.status);
    const payload = await res.json();
    renderAll(payload);
    fails = 0;
  } catch (e) {
    fails++;
    if (fails > 2) {
      const light = $('#sync-light');
      const label = $('#sync-label');
      light.classList.add('err');
      label.classList.add('err');
      label.textContent = 'NO SIGNAL';
    }
  }
}

tick();
setInterval(tick, 15000);