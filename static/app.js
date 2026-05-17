/* WATCH OOZE — frontend logic (Alpenglow cluster) */

const $ = (sel) => document.querySelector(sel);

// ───────── expansion state (persists across polls) ─────────
let isExpanded = false;
let lastNet = null;
let lastVal = null;

// ───────── formatters ─────────

function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  if (typeof n === 'string') return n;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtSol(s) {
  if (s === null || s === undefined) return '—';
  if (s >= 1e6) return (s / 1e6).toFixed(2) + 'M';
  if (s >= 1e3) return (s / 1e3).toFixed(1) + 'K';
  return s.toFixed(2);
}

function shortKey(k) {
  if (!k || typeof k !== 'string') return '—';
  if (k.length <= 14) return k;
  return k.slice(0, 6) + '…' + k.slice(-6);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ───────── render rows ─────────

function renderRow(v, isOurs, maxStake) {
  const tr = document.createElement('tr');
  tr.className = isOurs ? 'row-ours' : 'row-other';

  const identity = isOurs ? v.identity : shortKey(v.identity);
  const tagHtml = isOurs
    ? '<span class="tag tag-ours">OOZE</span>'
    : '<span class="tag">VALIDATOR</span>';

  const stakePct = maxStake > 0 ? Math.round((v.stake / maxStake) * 100) : 0;
  const statusColor = v.status === 'active' ? 'var(--phos)' : 'var(--err)';

  tr.innerHTML = `
    <td class="col-validator">
      <div class="cell-validator">
        ${tagHtml}
        <code class="cell-pubkey">${escapeHtml(identity)}</code>
      </div>
    </td>
    <td class="col-vote">
      <div class="cell-num">${escapeHtml(shortKey(v.vote_account))}</div>
    </td>
    <td class="col-stake">
      <div class="cell-num cell-num-strong">${fmtSol(v.stake)} ◎</div>
      <div class="cell-sub" style="text-align:right">
        <span style="display:inline-block;width:${stakePct}px;max-width:60px;height:2px;background:currentColor;vertical-align:middle;opacity:0.4"></span>
      </div>
    </td>
    <td class="col-votes">
      <div class="cell-num cell-num-strong">${fmtNum(v.last_vote)}</div>
      <div class="cell-sub">last vote</div>
    </td>
    <td class="col-uptime">
      <div class="cell-num cell-num-strong">${fmtNum(v.credits)}</div>
      <div class="cell-sub">credits</div>
    </td>
    <td class="col-epoch">
      <div class="cell-num" style="color:${statusColor}">${v.status ? v.status.toUpperCase() : '—'}</div>
    </td>
  `;

  return tr;
}

// ───────── render all ─────────

function renderAll(netPayload, valPayload) {
  // status strip
  $('#strip-count').textContent = fmtNum(valPayload.active_count);
  $('#strip-slot').textContent = fmtNum(netPayload.slot);
  $('#strip-epoch').textContent = fmtNum(netPayload.epoch);
  $('#strip-total').textContent = fmtSol(valPayload.total_stake) + ' ◎';

  // sync indicator
  const light = $('#sync-light');
  const label = $('#sync-label');
  light.classList.remove('err');
  label.classList.remove('err');
  label.textContent = 'SYNC';

  // network name
  const netEl = $('#net-foot');
  if (netEl) netEl.textContent = (netPayload.network || 'alpenglow').toUpperCase();
  const tpsEl = $('#meta-tps');
  if (tpsEl && netPayload.slot_index != null && netPayload.slots_in_epoch) {
    const pct = ((netPayload.slot_index / netPayload.slots_in_epoch) * 100).toFixed(1);
    tpsEl.textContent = pct + '%';
  }

  const validators = valPayload.validators || [];
  const maxStake = Math.max(...validators.map(v => v.stake || 0));

  const ours = validators.find(v => v.is_mine);
  const others = validators.filter(v => !v.is_mine);

  const tbody = $('#rows');
  tbody.innerHTML = '';

  if (validators.length === 0) {
    const tr = document.createElement('tr');
    tr.className = 'empty-row';
    tr.innerHTML = '<td colspan="6">// no validators found</td>';
    tbody.appendChild(tr);
    return;
  }

  if (ours) tbody.appendChild(renderRow(ours, true, maxStake));

  const VISIBLE = 20;
  const toShow = isExpanded ? others : others.slice(0, VISIBLE);
  toShow.forEach(v => tbody.appendChild(renderRow(v, false, maxStake)));

  if (others.length > VISIBLE) {
    const tr = document.createElement('tr');
    tr.id = 'expand-row';
    tr.className = 'empty-row';
    tr.style.cursor = 'pointer';
    if (isExpanded) {
      tr.innerHTML = `<td colspan="6" style="text-align:center;letter-spacing:2px;color:var(--phos-soft)">// collapse</td>`;
      tr.onclick = () => {
        isExpanded = false;
        renderAll(lastNet, lastVal);
      };
    } else {
      tr.innerHTML = `<td colspan="6" style="text-align:center;letter-spacing:2px;color:var(--phos-soft)">// ${others.length - VISIBLE} more validators — click to expand</td>`;
      tr.onclick = () => {
        isExpanded = true;
        renderAll(lastNet, lastVal);
      };
    }
    tbody.appendChild(tr);
  }
}

// ───────── poll ─────────

let fails = 0;

async function tick() {
  try {
    const [netRes, valRes] = await Promise.all([
      fetch('/api/network', { cache: 'no-store' }),
      fetch('/api/validators', { cache: 'no-store' })
    ]);
    if (!netRes.ok || !valRes.ok) throw new Error('http error');
    const [netPayload, valPayload] = await Promise.all([netRes.json(), valRes.json()]);
    if (netPayload.error || valPayload.error) throw new Error(netPayload.error || valPayload.error);
    lastNet = netPayload;
    lastVal = valPayload;
    renderAll(netPayload, valPayload);
    fails = 0;
  } catch (e) {
    fails++;
    if (fails > 2) {
      $('#sync-light').classList.add('err');
      $('#sync-label').classList.add('err');
      $('#sync-label').textContent = 'NO SIGNAL';
    }
  }
}

tick();
setInterval(tick, 10000);