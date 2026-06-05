/* WATCH OOZE — validator detail modal (additive; loaded after app.js)
   Grid-of-boxes layout (mockup style): top stat row + 2-col panel grid +
   full-width OOZE feature panel on the validator's own row.
   Single view = rich grid; compare = two columns side by side.
*/
(function () {
  const SYSHEALTH_URL = ''; // system-health disabled

  const vdNum = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString());
  const vdSol = (s) => {
    if (s === null || s === undefined) return '—';
    if (s >= 1e6) return (s / 1e6).toFixed(2) + 'M';
    if (s >= 1e3) return (s / 1e3).toFixed(1) + 'K';
    return Number(s).toFixed(2);
  };
  const vdShort = (k) => (!k ? '—' : k.length <= 14 ? k : k.slice(0, 6) + '…' + k.slice(-6));
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const overlay = document.createElement('div');
  overlay.className = 'vd-overlay';
  overlay.innerHTML = `
    <div class="vd-modal">
      <div class="vd-head">
        <span class="vd-title">VALIDATOR DETAIL</span>
        <div class="vd-actions">
          <button class="vd-btn" id="vd-compare-toggle">COMPARE</button>
          <button class="vd-btn vd-close" id="vd-close" aria-label="close">×</button>
        </div>
      </div>
      <div class="vd-body" id="vd-body"><div class="vd-loading">// loading…</div></div>
      <div class="vd-picker" id="vd-picker" style="display:none">
        <select id="vd-picker-sel"><option value="">// select a validator to compare…</option></select>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const body = overlay.querySelector('#vd-body');
  const picker = overlay.querySelector('#vd-picker');
  const pickerSel = overlay.querySelector('#vd-picker-sel');
  let compareMode = false, primaryVote = null, secondaryVote = null;

  function openOverlay() { overlay.classList.add('open'); }
  function closeOverlay() {
    overlay.classList.remove('open');
    compareMode = false; secondaryVote = null;
    overlay.querySelector('#vd-compare-toggle').classList.remove('active');
    picker.style.display = 'none';
    body.classList.remove('compare');
  }
  overlay.querySelector('#vd-close').onclick = closeOverlay;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeOverlay(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeOverlay(); });

  async function fetchDetail(voteAccount) {
    const r = await fetch('/api/validator/' + encodeURIComponent(voteAccount), { cache: 'no-store' });
    if (!r.ok) throw new Error('http ' + r.status);
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    return j;
  }

  // a stat card (top row)
  function stat(label, val, sub) {
    return `<div class="vd-stat"><div class="vd-stat-l">${label}</div><div class="vd-stat-v">${val}</div>${sub ? `<div class="vd-stat-s">${sub}</div>` : '<div class="vd-stat-s">&nbsp;</div>'}</div>`;
  }
  // a key/value row inside a panel
  function kv(k, v, vcls) {
    return `<div class="vd-r"><span class="k">${k}</span><span class="v ${vcls || ''}">${v}</span></div>`;
  }
  // a bordered panel box
  function panel(title, inner, cls) {
    return `<div class="vd-panel ${cls || ''}"><h3>${title}</h3>${inner}</div>`;
  }
  function bar(pct, cls) {
    const c = pct == null ? 0 : Math.min(100, pct);
    return `<div class="vd-lagbar${cls ? ' ' + cls : ''}"><div style="width:${c}%"></div></div>`;
  }

  // render ONE validator as a full grid (used for single view)
  function renderGrid(d) {
    const isMine = d.is_mine;

    let stCls = 'active', stTxt = 'VOTING';
    if (d.status === 'delinquent') { stCls = 'delinquent'; stTxt = 'DELINQUENT'; }
    else if (d.lag != null && d.lag > 64) { stCls = 'warn'; stTxt = 'LAGGING'; }

    const lag = d.lag;
    const lagPct = lag == null ? 0 : Math.min(100, (lag / 150) * 100);
    const lagCls = lag == null ? '' : lag > 128 ? 'bad' : lag > 32 ? 'warn' : '';

    const hist = d.credit_history || [];
    const maxC = Math.max(1, ...hist.map((h) => h.credits));
    const spark = hist.map((h) =>
      `<div class="bar" style="height:${Math.max(6, (h.credits / maxC) * 100)}%" title="epoch ${h.epoch}: ${vdNum(h.credits)}"></div>`
    ).join('');

    const rankTxt = d.rank ? `#${d.rank} / ${d.active_count}` : '—';
    const skipTxt = d.skip_rate == null ? '—' : d.skip_rate + '%';
    const skipCls = d.skip_rate == null ? '' : d.skip_rate > 30 ? 'bad' : d.skip_rate > 10 ? 'warn' : '';

    let lastBlockInner;
    if (d.last_block) {
      const lb = d.last_block;
      lastBlockInner = kv('SLOT', vdNum(lb.slot)) + kv('TRANSACTIONS', vdNum(lb.tx_count))
        + kv('TOTAL FEES', lb.total_fee_sol + ' ◎') + kv('COMPUTE UNITS', vdNum(lb.total_compute_units));
    } else {
      lastBlockInner = `<div class="vd-empty">no block produced this epoch yet</div>`;
    }

    const tag = isMine ? '<span class="vd-tag ours">OOZE</span>' : '<span class="vd-tag">VALIDATOR</span>';

    // header band
    const header = `
      <div class="vd-gridhead">
        <div>${tag}<div class="vd-status ${stCls}">${stTxt}</div></div>
        <div class="vd-idcol">
          <div class="vd-id"><span class="lbl">IDENTITY</span>${esc(d.identity || '—')}</div>
          <div class="vd-id"><span class="lbl">VOTE ACCOUNT</span>${esc(d.vote_account || '—')}</div>
        </div>
      </div>`;

    // top stat row (4 across)
    const statRow = `
      <div class="vd-statrow">
        ${stat('ACTIVE STAKE', vdSol(d.stake) + ' ◎')}
        ${stat('STAKE RANK', rankTxt)}
        ${stat('CREDITS', vdNum(d.this_epoch_credits), 'epoch ' + (d.epoch ?? '—'))}
        ${stat('NEXT LEADER', d.next_leader_in != null ? vdNum(d.next_leader_in) : '—', 'slots away')}
      </div>`;

    // 2-col panel grid
    const votePanel = panel('STAKE & VOTE',
      kv('COMMISSION', d.commission != null ? d.commission + '%' : '—')
      + kv('LAST VOTE', vdNum(d.last_vote))
      + kv('VOTE LAG', lag == null ? '—' : vdNum(lag) + ' slots')
      + bar(lagPct, lagCls)
      + kv('ROOT SLOT', vdNum(d.root_slot), 'dim')
    );

    const prodPanel = panel('BLOCK PRODUCTION',
      kv('LEADER SLOTS (EPOCH)', vdNum(d.leader_slots))
      + kv('BLOCKS PRODUCED', vdNum(d.blocks_produced))
      + kv('SKIP RATE', skipTxt, skipCls)
      + kv('CLIENT VERSION', esc(d.version || 'unknown'), 'dim')
    );

    const lastBlockPanel = panel('LAST PRODUCED BLOCK', lastBlockInner);

    const creditPanel = panel('CREDITS / EPOCH (last ' + hist.length + ')',
      `<div class="vd-spark">${spark || '<div class="bar" style="height:6%"></div>'}</div>`
    );

    const gridPanels = `<div class="vd-grid2">${votePanel}${prodPanel}${lastBlockPanel}${creditPanel}</div>`;

    // full-width OOZE feature panel (mine only)
    const oozePanel = isMine ? panel('FAIR ORDERING',
      `<div class="vd-ooze-line">
         <span>SCHEDULER</span><span class="v" style="color:var(--phos,#00ff41)">method: ooze</span>
       </div>
       <div class="vd-ooze-line">
         <span>STATUS</span><span class="v vd-engaged">ENGAGED</span>
       </div>
       <div class="vd-ooze-note">VRF-shuffled block ordering — transaction position cannot be bought. Priority fees collected as revenue but no longer determine sequence.</div>`,
      'feature') : '';

    return `<div class="vd-gridwrap">${header}${statRow}${gridPanels}${oozePanel}</div>`;
  }

  // render ONE validator as a single compact column (used for compare)
  function renderCompactCol(d) {
    const isMine = d.is_mine;
    let stCls = 'active', stTxt = 'VOTING';
    if (d.status === 'delinquent') { stCls = 'delinquent'; stTxt = 'DELINQUENT'; }
    else if (d.lag != null && d.lag > 64) { stCls = 'warn'; stTxt = 'LAGGING'; }
    const lag = d.lag;
    const lagPct = lag == null ? 0 : Math.min(100, (lag / 150) * 100);
    const lagCls = lag == null ? '' : lag > 128 ? 'bad' : lag > 32 ? 'warn' : '';
    const rankTxt = d.rank ? `#${d.rank} / ${d.active_count}` : '—';
    const skipTxt = d.skip_rate == null ? '—' : d.skip_rate + '%';
    const skipCls = d.skip_rate == null ? '' : d.skip_rate > 30 ? 'bad' : d.skip_rate > 10 ? 'warn' : '';
    const tag = isMine ? '<span class="vd-tag ours">OOZE</span>' : '<span class="vd-tag">VALIDATOR</span>';
    const lb = d.last_block;
    return `
      <div class="vd-col">
        ${tag}
        <div class="vd-status ${stCls}">${stTxt}</div>
        <div class="vd-id-block">
          <div class="vd-id"><span class="lbl">IDENTITY</span>${esc(d.identity || '—')}</div>
          <div class="vd-id"><span class="lbl">VOTE ACCOUNT</span>${esc(d.vote_account || '—')}</div>
        </div>
        <div class="vd-section">STAKE & VOTE</div>
        ${kv('ACTIVE STAKE', vdSol(d.stake) + ' ◎')}
        ${kv('STAKE RANK', rankTxt)}
        ${kv('COMMISSION', d.commission != null ? d.commission + '%' : '—')}
        ${kv('CREDITS (EPOCH ' + (d.epoch ?? '—') + ')', vdNum(d.this_epoch_credits))}
        ${kv('LAST VOTE', vdNum(d.last_vote))}
        ${kv('VOTE LAG', lag == null ? '—' : vdNum(lag) + ' slots')}
        ${bar(lagPct, lagCls)}
        <div class="vd-section">BLOCK PRODUCTION</div>
        ${kv('LEADER SLOTS', vdNum(d.leader_slots))}
        ${kv('BLOCKS PRODUCED', vdNum(d.blocks_produced))}
        ${kv('SKIP RATE', skipTxt, skipCls)}
        ${kv('NEXT LEADER IN', d.next_leader_in != null ? vdNum(d.next_leader_in) + ' slots' : '—')}
        <div class="vd-section">LAST PRODUCED BLOCK</div>
        ${lb ? (kv('SLOT', vdNum(lb.slot)) + kv('TXS', vdNum(lb.tx_count)) + kv('FEES', lb.total_fee_sol + ' ◎')) : '<div class="vd-empty">none yet</div>'}
        ${isMine ? '<div class="vd-section">FAIR ORDERING</div>' + kv('STATUS', 'ENGAGED') : ''}
      </div>`;
  }

  async function renderBody() {
    body.innerHTML = '<div class="vd-loading">// loading…</div>';
    try {
      if (compareMode && secondaryVote) {
        const [a, b] = await Promise.all([fetchDetail(primaryVote), fetchDetail(secondaryVote)]);
        body.classList.add('compare');
        body.innerHTML = renderCompactCol(a) + renderCompactCol(b);
      } else {
        const a = await fetchDetail(primaryVote);
        body.classList.remove('compare');
        body.innerHTML = renderGrid(a);
      }
    } catch (e) {
      body.innerHTML = '<div class="vd-err">// detail error: ' + esc(e.message) + '</div>';
    }
  }

  function fillPicker() {
    const vals = (window.lastVal && window.lastVal.validators) || [];
    pickerSel.innerHTML = '<option value="">// select a validator to compare…</option>';
    vals.forEach((v) => {
      if (v.vote_account === primaryVote) return;
      const o = document.createElement('option');
      o.value = v.vote_account;
      o.textContent = (v.is_mine ? '[OOZE] ' : '') + vdShort(v.identity) + '  ·  ' + vdSol(v.stake) + ' ◎';
      pickerSel.appendChild(o);
    });
  }
  pickerSel.onchange = () => { secondaryVote = pickerSel.value || null; renderBody(); };

  overlay.querySelector('#vd-compare-toggle').onclick = function () {
    compareMode = !compareMode;
    this.classList.toggle('active', compareMode);
    picker.style.display = compareMode ? 'block' : 'none';
    if (compareMode) fillPicker(); else { secondaryVote = null; renderBody(); }
  };

  function openDetail(voteAccount) {
    primaryVote = voteAccount; secondaryVote = null;
    openOverlay(); renderBody();
  }
  window.oozeOpenDetail = openDetail;

  const tbody = document.querySelector('#rows');
  if (tbody) {
    tbody.addEventListener('click', (e) => {
      const tr = e.target.closest('tr');
      if (!tr || tr.classList.contains('empty-row') || tr.id === 'expand-row') return;
      const voteEl = tr.querySelector('.col-vote .cell-num');
      if (!voteEl) return;
      const shortVote = voteEl.textContent.trim();
      const vals = (window.lastVal && window.lastVal.validators) || [];
      const match = vals.find((v) => vdShort(v.vote_account) === shortVote);
      if (match) openDetail(match.vote_account);
    });
  }
})();