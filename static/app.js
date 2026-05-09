/* OOZE WATCH — frontend logic */

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
    if (s >= 1e6) return (s / 1e6).toFixed(2) + 'M ◎';
    if (s >= 1e3) return (s / 1e3).toFixed(1) + 'K ◎';
    return s.toFixed(2) + ' ◎';
  }
  // long form: full decimals up to 6
  if (s >= 1e6) return (s / 1e6).toFixed(3) + 'M ◎';
  if (s >= 1e3) return s.toFixed(2) + ' ◎';
  if (s < 0.001) return s.toFixed(9) + ' ◎';
  return s.toFixed(6) + ' ◎';
}

function fmtLamports(n) {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString() + ' lamports';
}

function shortKey(k) {
  if (!k || typeof k !== 'string') return '—';
  if (k.length <= 12) return k;
  return k.slice(0, 4) + '…' + k.slice(-4);
}

// ───────── render ─────────

function renderCard(record, isOurs) {
  const tpl = $('#card-tpl').content.cloneNode(true);
  const card = tpl.querySelector('.validator-card');
  if (isOurs) card.classList.add('ours');

  card.querySelector('.card-pubkey').textContent = isOurs
    ? record.validator
    : shortKey(record.validator);

  const tag = card.querySelector('.card-tag');
  if (isOurs) {
    tag.textContent = 'OOZE';
    tag.classList.add('ours-tag');
    tag.classList.remove('dim');
  } else {
    tag.textContent = 'VALIDATOR';
  }

  card.querySelector('.uptime').textContent = (record.uptimePct ?? 0).toFixed(2) + '%';
  card.querySelector('.uptime-bps').textContent = (record.uptimeBps ?? 0) + ' bps';

  card.querySelector('.stake').textContent = fmtSol(record.delegatedStakeSol, { compact: false });
  card.querySelector('.stake-lamports').textContent = fmtLamports(record.delegatedStakeLamports);

  card.querySelector('.votes').textContent = fmtNum(record.votesCast);

  card.querySelector('.subsidy').textContent = fmtSol(record.lifetimeSubsidySol, { compact: false });
  card.querySelector('.subsidy-lamports').textContent = fmtLamports(record.lifetimeSubsidyLamports);

  card.querySelector('.last-epoch').textContent = record.lastDistributionEpoch ?? '—';
  card.querySelector('.last-slot').textContent = (record.lastMetricsSlot ?? '—').toLocaleString?.() ?? record.lastMetricsSlot ?? '—';
  card.querySelector('.last-nonce').textContent = record.lastMetricsNonce ?? '—';

  return tpl;
}

function renderAll(payload) {
  const ourPubkey = payload.ourValidator;
  const records = payload.validators || [];

  // status strip
  $('#strip-count').textContent = fmtNum(payload.registeredCount);
  $('#strip-slot').textContent = fmtNum(payload.slot);
  $('#strip-epoch').textContent = fmtNum(payload.epoch);

  const totalLamports = records.reduce((s, r) => s + (r.lifetimeSubsidyLamports || 0), 0);
  $('#strip-total').textContent = fmtSol(totalLamports / 1e9, { compact: true });

  $('#status-dot').classList.add('live');
  $('#status-dot').classList.remove('err');
  $('#status-text').textContent = 'live';

  $('#rpc-foot').textContent = payload.rpcUrl || '—';

  // ours
  const oursWrap = $('#ours-wrap');
  const oursCard = $('#ours-card');
  oursCard.innerHTML = '';
  const ours = records.find((r) => r.validator === ourPubkey);
  if (ours) {
    oursWrap.hidden = false;
    oursCard.appendChild(renderCard(ours, true).querySelector('.validator-card'));
  } else {
    oursWrap.hidden = true;
  }

  // others
  const grid = $('#validators-grid');
  grid.innerHTML = '';
  const others = records.filter((r) => r.validator !== ourPubkey);
  if (others.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'dim';
    empty.style.padding = '20px';
    empty.style.textAlign = 'center';
    empty.style.gridColumn = '1 / -1';
    empty.textContent = '// no other validators in registry';
    grid.appendChild(empty);
  } else {
    for (const record of others) {
      grid.appendChild(renderCard(record, false));
    }
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
      $('#status-dot').classList.remove('live');
      $('#status-dot').classList.add('err');
      $('#status-text').textContent = 'rpc unreachable';
    }
  }
}

tick();
setInterval(tick, 15000);