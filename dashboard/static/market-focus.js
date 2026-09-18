(() => {
  const host = document.getElementById('mntMarketFocusHost');
  if (!host) return;

  const state = { loading: false, data: null };

  function num(value, digits = 1) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(digits) : '—';
  }

  function money(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : '—';
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function directionClass(value) {
    const direction = String(value || '').toUpperCase();
    return direction === 'LONG' ? 'positive' : direction === 'SHORT' ? 'negative' : 'neutral';
  }

  function sectorCard(row, side) {
    if (!row) return '';
    const strength = Number(row.strength || 0);
    const sign = strength > 0 ? '+' : '';
    return `
      <button class="mnt-focus-sector ${side}" type="button" data-mnt-symbol="${escapeHtml(row.symbol)}">
        <span><strong>${escapeHtml(row.sector || row.symbol)}</strong><small>${escapeHtml(row.symbol)}</small></span>
        <span class="mnt-focus-sector-metrics"><b>${sign}${num(strength)}</b><small>${num(row.momentum_30m_pct, 2)}% · RVOL ${num(row.rvol, 2)}</small></span>
      </button>`;
  }

  function moverRow(row) {
    const css = directionClass(row.direction);
    return `
      <button type="button" class="mnt-focus-mover" data-mnt-symbol="${escapeHtml(row.symbol)}" data-mnt-run="true">
        <span><strong>${escapeHtml(row.symbol)}</strong><small>${escapeHtml(row.sector || row.sector_etf || '')}</small></span>
        <span class="${css}">${escapeHtml(row.direction || 'NEUTRAL')}</span>
        <span>${num(row.momentum_30m_pct, 2)}%</span>
        <span>${num(row.rvol, 2)}×</span>
        <span class="score">${num(row.focus_score, 0)}</span>
      </button>`;
  }

  function queueRow(row, index) {
    return `
      <button type="button" class="mnt-focus-queue-row" data-mnt-symbol="${escapeHtml(row.symbol)}" data-mnt-run="true">
        <span class="mnt-focus-rank">${index + 1}</span>
        <span><strong>${escapeHtml(row.symbol)}</strong><small>${escapeHtml(row.lane || '')}</small></span>
        <span class="mnt-focus-reason">${escapeHtml(row.reason || '')}</span>
      </button>`;
  }

  function coreCard(row) {
    const css = directionClass(row.direction);
    return `
      <button type="button" class="mnt-focus-core-card" data-mnt-symbol="${escapeHtml(row.symbol)}" data-mnt-run="true">
        <span><strong>${escapeHtml(row.symbol)}</strong><small>${escapeHtml(row.provider || 'market')}</small></span>
        <b class="${css}">${escapeHtml(row.direction || '—')}</b>
        <span>${money(row.price)}</span>
        <small>Score ${num(row.score, 0)} · RVOL ${num(row.rvol, 2)}</small>
      </button>`;
  }

  function mag7Chip(row) {
    const css = directionClass(row.direction);
    return `<button type="button" class="mnt-focus-mag-chip ${css}" data-mnt-symbol="${escapeHtml(row.symbol)}" data-mnt-run="true"><strong>${escapeHtml(row.symbol)}</strong><span>${escapeHtml(row.direction || '—')}</span><small>${num(row.momentum_30m_pct, 2)}% · ${num(row.rvol, 2)}×</small></button>`;
  }

  function render(data) {
    state.data = data;
    const tone = data.market_tone || {};
    const spx = data.spx || {};
    const fallbacks = Array.isArray(data.fallback_symbols) ? data.fallback_symbols : [];
    const providerLabel = fallbacks.length ? `Mixed · ${fallbacks.length} fallback` : 'Schwab primary';
    const toneClass = tone.state === 'RISK_ON' ? 'positive' : tone.state === 'RISK_OFF' ? 'negative' : 'neutral';

    host.innerHTML = `
      <section class="mnt-focus-shell" aria-live="polite">
        <div class="mnt-focus-command">
          <div>
            <div class="eyebrow">MARKET FOCUS MODE</div>
            <h2>Where is the action today?</h2>
            <p>Fast-scan the market, then spend Kronos compute on SPY/QQQ, the most active Mag-7 names and movers aligned with the sectors actually leading or lagging.</p>
          </div>
          <button type="button" id="mntFocusRefresh" class="ghost-button">Refresh focus</button>
        </div>

        <div class="mnt-focus-pulse-grid">
          <div class="mnt-focus-pulse-card"><span>Market tone</span><strong class="${toneClass}">${escapeHtml(tone.state || 'UNKNOWN')}</strong><small>${escapeHtml(tone.note || '')}</small></div>
          <div class="mnt-focus-pulse-card"><span>SPX context</span><strong>${spx.available ? money(spx.price) : 'Unavailable'}</strong><small>${spx.available ? 'Schwab index context' : escapeHtml(spx.reason || '')}</small></div>
          <div class="mnt-focus-pulse-card"><span>Data</span><strong>${providerLabel}</strong><small>${escapeHtml(data.generated_at ? new Date(data.generated_at).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : '')}</small></div>
        </div>

        <div class="mnt-focus-section">
          <div class="mnt-focus-title"><div><div class="eyebrow">CORE CONTEXT</div><h3>SPY / QQQ</h3></div><span>Always fast-scanned and prioritized for deep review</span></div>
          <div class="mnt-focus-core-grid">${(data.core || []).map(coreCard).join('')}</div>
        </div>

        <div class="mnt-focus-section">
          <div class="mnt-focus-title"><div><div class="eyebrow">MAG 7</div><h3>Active leadership</h3></div><span>All seven are scanned; the most active compete for Kronos slots</span></div>
          <div class="mnt-focus-mag-grid">${(data.mag7 || []).map(mag7Chip).join('')}</div>
        </div>

        <div class="mnt-focus-two-col">
          <div class="mnt-focus-section">
            <div class="mnt-focus-title"><div><div class="eyebrow">SECTOR RACE</div><h3>Leading</h3></div></div>
            <div class="mnt-focus-sector-list">${(data.leading_sectors || []).map(row => sectorCard(row, 'leader')).join('') || '<div class="muted">No clear leader yet.</div>'}</div>
          </div>
          <div class="mnt-focus-section">
            <div class="mnt-focus-title"><div><div class="eyebrow">SECTOR RACE</div><h3>Lagging</h3></div></div>
            <div class="mnt-focus-sector-list">${(data.lagging_sectors || []).map(row => sectorCard(row, 'laggard')).join('') || '<div class="muted">No clear laggard yet.</div>'}</div>
          </div>
        </div>

        <div class="mnt-focus-two-col mnt-focus-main-grid">
          <div class="mnt-focus-section">
            <div class="mnt-focus-title"><div><div class="eyebrow">SECTOR MOVERS</div><h3>Best aligned names</h3></div><span>Click a name to open Trade Desk + run MnT</span></div>
            <div class="mnt-focus-mover-head"><span>Symbol</span><span>Bias</span><span>30m</span><span>RVOL</span><span>Focus</span></div>
            <div class="mnt-focus-mover-list">${(data.movers || []).slice(0, 10).map(moverRow).join('') || '<div class="muted">Waiting for mover data.</div>'}</div>
          </div>
          <div class="mnt-focus-section">
            <div class="mnt-focus-title"><div><div class="eyebrow">KRONOS QUEUE</div><h3>Dynamic deep review</h3></div><span>Your My Focus + sticky PRE-TRIGGERs are inserted ahead of this queue by the worker</span></div>
            <div class="mnt-focus-queue">${(data.priority_queue || []).map(queueRow).join('') || '<div class="muted">Queue is building.</div>'}</div>
          </div>
        </div>
      </section>`;

    document.getElementById('mntFocusRefresh')?.addEventListener('click', () => load(true));
  }

  function openSymbol(symbol, analyze) {
    const input = document.getElementById('symbolInput');
    const form = document.getElementById('symbolForm');
    if (!input || !form) return;
    window.MnTWorkspace?.openTab('trade');
    input.value = String(symbol || '').toUpperCase();
    form.requestSubmit();
    if (analyze) setTimeout(() => document.getElementById('runFusion')?.click(), 350);
  }

  host.addEventListener('click', event => {
    const button = event.target.closest('[data-mnt-symbol]');
    if (!button) return;
    const symbol = button.dataset.mntSymbol;
    if (!symbol || symbol.startsWith('XL') || symbol === 'SMH') return;
    event.preventDefault();
    openSymbol(symbol, button.dataset.mntRun === 'true');
  });

  async function load(force = false) {
    if (state.loading) return;
    state.loading = true;
    if (!state.data) host.innerHTML = '<div class="panel"><div class="muted">Building Market Focus Mode…</div></div>';
    try {
      const url = force ? `/api/market/focus?_=${Date.now()}` : '/api/market/focus';
      const response = await fetch(url, { cache: force ? 'no-store' : 'default' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      render(data);
    } catch (error) {
      host.innerHTML = `<div class="panel"><strong>Market Focus unavailable</strong><p class="muted">${escapeHtml(error.message)}</p></div>`;
    } finally {
      state.loading = false;
    }
  }

  window.addEventListener('mnt:workspace-changed', event => {
    if (event.detail?.tab === 'market' && !state.data) load();
  });

  setInterval(() => {
    if (window.MnTWorkspace?.activeTab() === 'market') load();
  }, 60000);

  if (window.MnTWorkspace?.activeTab() === 'market') load();
})();
