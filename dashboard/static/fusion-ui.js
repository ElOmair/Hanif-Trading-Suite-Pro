(() => {
  function pick(obj, keys) {
    if (!obj || typeof obj !== 'object') return undefined;
    for (const key of keys) {
      if (obj[key] !== undefined && obj[key] !== null && obj[key] !== '') return obj[key];
    }
    return undefined;
  }

  function decisionLabel(decision) {
    if (!decision) return 'UNKNOWN';
    if (typeof decision === 'string') return decision.toUpperCase();
    return String(pick(decision, ['decision', 'action', 'state', 'status']) || 'UNKNOWN').toUpperCase();
  }

  function money(value) {
    return Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';
  }

  function ensureUi() {
    const controls = document.querySelector('.kronos-live-controls');
    const optionCard = document.querySelector('.options-card');
    if (!controls || !optionCard || document.getElementById('runFusion')) return;

    const button = document.createElement('button');
    button.id = 'runFusion';
    button.type = 'button';
    button.className = 'ghost-button';
    button.textContent = 'Evaluate setup';
    controls.appendChild(button);

    let host = document.getElementById('fusionResults');
    if (!host) {
      host = document.createElement('div');
      host.id = 'fusionResults';
      host.className = 'empty-state';
      host.textContent = 'Decision Engine and option research results will appear here.';
      optionCard.appendChild(host);
    }

    button.addEventListener('click', async () => {
      const symbol = (document.getElementById('activeSymbol')?.textContent || '').trim().toUpperCase();
      if (!symbol) return;
      button.disabled = true;
      button.textContent = 'Evaluating…';
      host.textContent = `${symbol}: refreshing market data, running Kronos, then evaluating the setup…`;

      try {
        const res = await fetch(`/api/kronos/fusion/${encodeURIComponent(symbol)}`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

        const label = decisionLabel(data.decision);
        const technical = data.technical || {};
        const kronos = data.kronos || {};
        const options = Array.isArray(data.options) ? data.options : [];

        let html = `<div><strong>Decision Engine: ${label}</strong></div>`;
        html += `<div class="fineprint">Technical: ${technical.signal || '—'} · Kronos: ${kronos.final_bias || '—'} · Stability: ${kronos.stability || '—'}</div>`;

        if (options.length) {
          const c = options[0] || {};
          const contract = pick(c, ['symbol', 'contract_symbol', 'option_symbol']) || 'Top research candidate';
          html += `<div style="margin-top:10px"><strong>${contract}</strong></div>`;
          html += `<div class="fineprint">Strike ${money(pick(c, ['strike', 'strike_price']))} · Expiry ${pick(c, ['expiration', 'expiry', 'expiration_date']) || '—'} · DTE ${pick(c, ['dte']) ?? '—'} · Bid/Ask ${money(pick(c, ['bid', 'bid_price']))}/${money(pick(c, ['ask', 'ask_price']))} · Delta ${pick(c, ['delta']) ?? '—'} · Fit ${pick(c, ['score', 'total_score', 'fit_score']) ?? '—'}</div>`;
          html += '<div class="fineprint">Mechanical research fit only; the dashboard does not place orders.</div>';
        } else {
          html += '<div class="fineprint" style="margin-top:10px">No option-contract scan was produced unless the existing Decision Engine returned CONFIRM.</div>';
        }
        host.innerHTML = html;
      } catch (err) {
        host.textContent = `Evaluation error: ${err.message}`;
      } finally {
        button.disabled = false;
        button.textContent = 'Evaluate setup';
      }
    });
  }

  const timer = setInterval(() => {
    ensureUi();
    if (document.getElementById('runFusion')) clearInterval(timer);
  }, 250);
  setTimeout(() => clearInterval(timer), 10000);
})();
