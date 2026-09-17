(() => {
  const money = value => Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';
  const pct = value => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : '—';
  const safe = (value, fallback = '—') => value === undefined || value === null || value === '' ? fallback : String(value);

  async function getJson(url) {
    const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  function decisionLabel(value) {
    if (!value) return 'UNKNOWN';
    if (typeof value === 'string') return value.toUpperCase();
    return String(value.decision || value.action || value.state || value.status || 'UNKNOWN').toUpperCase();
  }

  function ensureHost() {
    const card = document.querySelector('.options-card');
    if (!card) return null;
    let host = document.getElementById('mntSchwabFusion');
    if (host) return host;
    host = document.createElement('section');
    host.id = 'mntSchwabFusion';
    host.className = 'mnt-schwab-fit';
    host.innerHTML = '<div class="eyebrow">SCHWAB / THINKORSWIM</div><strong>Option-chain analysis</strong><div class="fineprint" style="margin-top:5px">Waiting for a MnT analysis.</div>';
    card.appendChild(host);
    return host;
  }

  function contextClass(relationship) {
    if (relationship === 'NEW') return 'good';
    if (relationship === 'ALREADY_EXPOSED' || relationship === 'MIXED') return 'caution';
    if (relationship === 'CONFLICT') return 'stop';
    return '';
  }

  function renderContext(context) {
    if (!context || context.available === false) {
      return `<div class="mnt-portfolio-context"><span class="mnt-context-label">Portfolio check</span><strong>NOT IN USE</strong><div class="fineprint" style="margin-top:5px">Schwab is being used for market-data and option-chain analysis only. MnT is not reading brokerage positions.</div></div>`;
    }
    const positions = context.positions || [];
    const details = positions.slice(0, 3).map(row => `${safe(row.symbol)} · value ${money(row.market_value)}`).join('<br>');
    return `
      <div class="mnt-portfolio-context ${contextClass(context.relationship)}">
        <span class="mnt-context-label">Portfolio check</span>
        <strong>${safe(context.relationship).replaceAll('_', ' ')}</strong>
        <div class="fineprint" style="margin-top:5px">${safe(context.action_note)}</div>
        <div class="mnt-schwab-fit-grid">
          <div><span>Existing exposure</span><strong>${money(context.existing_market_value)}</strong></div>
          <div><span>Concentration</span><strong>${pct(context.concentration_pct)}</strong></div>
          <div><span>Buying power</span><strong>${money(context.buying_power)}</strong></div>
          <div><span>Risk flag</span><strong>${safe(context.risk_level)}</strong></div>
        </div>
        ${details ? `<div class="fineprint" style="margin-top:6px">${details}</div>` : ''}
      </div>`;
  }

  function renderCandidates(payload, budget) {
    const rows = payload.candidates || [];
    if (!rows.length) {
      return `<div class="mnt-portfolio-context caution"><span class="mnt-context-label">Schwab option-chain check</span><strong>NO CONTRACT CLEARED</strong><div class="fineprint" style="margin-top:5px">No Schwab option met the ${money(budget)} budget and current liquidity/fit rules. MnT should not force a cheaper, lower-quality contract.</div></div>`;
    }
    const best = rows[0];
    return `
      <div class="mnt-portfolio-context good">
        <span class="mnt-context-label">Best Schwab contract to review</span>
        <strong>${safe(best.symbol)}</strong>
        <div class="fineprint" style="margin-top:5px">Analysis candidate only — use your current trading workflow if you decide to take it.</div>
        <div class="mnt-schwab-fit-grid">
          <div><span>Estimated cost</span><strong>${money(best.estimated_cost)}</strong></div>
          <div><span>MnT contract score</span><strong>${Number(best.score || 0).toFixed(1)}/100</strong></div>
          <div><span>Bid / Ask</span><strong>${money(best.bid)} / ${money(best.ask)}</strong></div>
          <div><span>Spread</span><strong>${pct(best.spread_pct)}</strong></div>
          <div><span>Delta</span><strong>${best.delta ?? '—'}</strong></div>
          <div><span>DTE</span><strong>${best.days_to_expiration ?? best.dte ?? '—'}</strong></div>
          <div><span>Volume</span><strong>${best.volume ?? '—'}</strong></div>
          <div><span>Open interest</span><strong>${best.open_interest ?? '—'}</strong></div>
        </div>
      </div>`;
  }

  async function renderFusion(data) {
    const host = ensureHost();
    if (!host) return;
    const technical = data.technical || {};
    const symbol = String(data.symbol || technical.symbol || document.getElementById('activeSymbol')?.textContent || '').trim().toUpperCase();
    const direction = String(technical.signal || data.mnt_score?.direction || '').trim().toUpperCase();
    const decision = decisionLabel(data.decision);
    if (!symbol || !['LONG', 'SHORT'].includes(direction)) {
      host.innerHTML = '<div class="eyebrow">SCHWAB / THINKORSWIM</div><strong>Option-chain analysis</strong><div class="fineprint" style="margin-top:5px">MnT needs a LONG or SHORT setup before checking Schwab contracts.</div>';
      return;
    }

    host.innerHTML = `<div class="eyebrow">SCHWAB / THINKORSWIM</div><strong>${symbol} option-chain analysis</strong><div class="fineprint" style="margin-top:5px">Checking Schwab market data and contract quality…</div>`;
    try {
      const status = await getJson('/api/schwab/status');
      if (!(status.authorized && status.refresh_token_valid)) {
        host.innerHTML = `<div class="eyebrow">SCHWAB / THINKORSWIM</div><strong>Market-data analysis not connected</strong><div class="fineprint" style="margin-top:5px">Connect Schwab to use quotes and option-chain analysis.</div><div style="margin-top:8px"><a class="ghost-button" href="/broker">Open Analysis Desk</a></div>`;
        return;
      }

      const budgetInput = Number(document.getElementById('tradeBudget')?.value);
      const storedBudget = Number(localStorage.getItem('mts.tradeBudget'));
      const budget = Number.isFinite(budgetInput) && budgetInput > 0 ? budgetInput : Number.isFinite(storedBudget) && storedBudget > 0 ? storedBudget : 300;
      const params = new URLSearchParams({ direction });
      const contextPromise = status.accounts_enabled
        ? getJson(`/api/schwab/portfolio/${encodeURIComponent(symbol)}/context?${params}`)
        : Promise.resolve({ available: false });

      const shouldScanContract = decision.includes('CONFIRM') || decision.includes('READY') || decision.includes('ARMED') || decision.includes('WATCH');
      const candidatePromise = shouldScanContract
        ? getJson(`/api/schwab/options/${encodeURIComponent(symbol)}/candidates?${new URLSearchParams({ direction, style: 'auto', max_contract_cost: String(budget), limit: '3' })}`)
        : Promise.resolve(null);

      const [context, candidates] = await Promise.all([contextPromise, candidatePromise]);
      let html = `<div class="eyebrow">SCHWAB / THINKORSWIM</div><strong>${symbol} option-chain analysis</strong>`;
      html += renderContext(context);
      if (candidates) html += renderCandidates(candidates, budget);
      else html += '<div class="fineprint" style="margin-top:8px">Contract scan skipped because the current setup is not close enough to an actionable state.</div>';
      host.innerHTML = html;

      if (context?.available !== false) window.dispatchEvent(new CustomEvent('mnt:portfolio-context', { detail: context }));
    } catch (error) {
      host.innerHTML = `<div class="eyebrow">SCHWAB / THINKORSWIM</div><strong>Option-chain analysis unavailable</strong><div class="fineprint" style="margin-top:5px">${safe(error.message)}</div>`;
    }
  }

  window.addEventListener('mnt:fusion-result', event => renderFusion(event.detail || {}));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureHost);
  else ensureHost();
})();
