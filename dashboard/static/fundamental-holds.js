(() => {
  const num = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const fmt = (value, digits = 1) => num(value) == null ? '—' : Number(value).toFixed(digits);

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  function trendScore(card) {
    const text = card.querySelector('.mnt-score')?.textContent || '';
    const match = text.match(/([0-9.]+)/);
    return match ? Number(match[1]) : null;
  }

  function combinedScore(trend, fundamental) {
    if (!Number.isFinite(trend)) return null;
    const fScore = num(fundamental?.score);
    const fCoverage = Math.max(0, Math.min(100, num(fundamental?.coverage_pct) ?? 0)) / 100;
    if (fScore == null || fCoverage <= 0) return { score: trend, coverage: 70 };
    const trendWeight = 70;
    const fundamentalWeight = 30 * fCoverage;
    return {
      score: (trend * trendWeight + fScore * fundamentalWeight) / (trendWeight + fundamentalWeight),
      coverage: trendWeight + fundamentalWeight,
    };
  }

  function render(card, symbol, fundamental) {
    const original = trendScore(card);
    const combined = combinedScore(original, fundamental);
    const scoreEl = card.querySelector('.mnt-score');
    if (combined && scoreEl) {
      scoreEl.textContent = `${Math.round(combined.score)}/100`;
      scoreEl.title = `Position score: trend + Schwab quote fundamentals · ${Math.round(combined.coverage)}% evidence coverage`;
    }

    let addendum = card.querySelector('.mnt-fundamental-addendum');
    if (!addendum) {
      addendum = document.createElement('div');
      addendum.className = 'mnt-fundamental-addendum';
      addendum.style.marginTop = '9px';
      addendum.style.paddingTop = '8px';
      addendum.style.borderTop = '1px solid rgba(148,163,184,.12)';
      card.insertBefore(addendum, card.querySelector('.mnt-open-idea'));
    }

    const label = fundamental.label || 'NO DATA';
    const eps = num(fundamental.eps);
    const pe = num(fundamental.pe_ratio);
    const range = num(fundamental.week_52_range_position_pct);
    const volume = num(fundamental.volume_ratio);
    addendum.innerHTML = `
      <div class="mnt-context-label">Schwab fundamental snapshot</div>
      <div class="mnt-action" style="margin:4px 0 6px">${label} · ${fundamental.score == null ? 'not enough data' : `${fmt(fundamental.score)}/100`}</div>
      <div class="mnt-mini-grid">
        <div><span>EPS</span><strong>${eps == null ? '—' : fmt(eps, 2)}</strong></div>
        <div><span>P/E</span><strong>${pe == null ? '—' : fmt(pe, 1)}</strong></div>
        <div><span>52-week position</span><strong>${range == null ? '—' : `${fmt(range, 0)}%`}</strong></div>
        <div><span>Recent volume</span><strong>${volume == null ? '—' : `${fmt(volume, 2)}× 1Y avg`}</strong></div>
      </div>
      <p class="mnt-why" style="margin-top:7px">${fundamental.note || 'Screening data only.'}</p>`;
    card.dataset.fundamentalsEnriched = 'true';

    const note = document.querySelector('#mntOpportunityShell .mnt-desk-note');
    if (note) note.textContent = '3–4 month position scores now combine real Alpaca daily trend data with available Schwab equity quote fundamentals. Schwab quote fundamentals are a screening layer, not a full financial-statement or analyst-estimate model.';
  }

  async function enrich() {
    const lane = document.getElementById('mntHoldLane');
    if (!lane) return;
    let status;
    try { status = await getJson('/api/schwab/status'); } catch (_) { return; }
    if (!(status.authorized && status.refresh_token_valid)) return;

    const cards = [...lane.querySelectorAll('.mnt-idea')].filter(card => card.dataset.fundamentalsEnriched !== 'true');
    for (const card of cards) {
      const symbol = card.querySelector('[data-mnt-symbol]')?.getAttribute('data-mnt-symbol');
      if (!symbol) continue;
      card.dataset.fundamentalsEnriched = 'loading';
      try {
        const fundamental = await getJson(`/api/schwab/fundamentals/${encodeURIComponent(symbol)}`);
        render(card, symbol, fundamental);
      } catch (_) {
        card.dataset.fundamentalsEnriched = 'error';
      }
    }
  }

  function start() {
    const timer = setInterval(() => {
      const lane = document.getElementById('mntHoldLane');
      if (!lane) return;
      clearInterval(timer);
      enrich();
      const observer = new MutationObserver(() => enrich());
      observer.observe(lane, { childList: true, subtree: true });
    }, 300);
    setTimeout(() => clearInterval(timer), 15000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
