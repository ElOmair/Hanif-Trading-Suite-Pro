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

  function number(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function loadSetting(key, fallback) {
    const n = Number(localStorage.getItem(key));
    return Number.isFinite(n) && n > 0 ? n : fallback;
  }

  function candidateDebit(candidate) {
    const ask = number(pick(candidate, ['ask', 'ask_price']));
    const bid = number(pick(candidate, ['bid', 'bid_price']));
    const mid = ask != null && bid != null && ask > 0 && bid > 0 ? (ask + bid) / 2 : null;
    const premium = ask && ask > 0 ? ask : mid;
    return premium && premium > 0 ? premium * 100 : null;
  }

  function noChaseState(technical, tradePlan) {
    const direction = String(technical?.signal || '').toUpperCase();
    const price = number(technical?.price);
    const atr = number(technical?.atr);
    const entryLow = number(pick(tradePlan, ['entry_low', 'entryLow'])) ?? number(technical?.entry_low);
    const entryHigh = number(pick(tradePlan, ['entry_high', 'entryHigh'])) ?? number(technical?.entry_high);
    let noChase = number(pick(tradePlan, ['no_chase', 'no_chase_price', 'chase_limit', 'chaseLimit']));

    if (noChase == null && atr != null) {
      if (direction === 'LONG' && entryHigh != null) noChase = entryHigh + atr * 0.25;
      if (direction === 'SHORT' && entryLow != null) noChase = entryLow - atr * 0.25;
    }

    let blocked = false;
    if (price != null && noChase != null) {
      blocked = direction === 'LONG' ? price > noChase : direction === 'SHORT' ? price < noChase : false;
    }

    return { blocked, noChase, price, entryLow, entryHigh };
  }

  function ensureUi() {
    const controls = document.querySelector('.kronos-live-controls');
    const optionCard = document.querySelector('.options-card');
    if (!controls || !optionCard || document.getElementById('runFusion')) return;

    const budget = document.createElement('input');
    budget.id = 'tradeBudget';
    budget.type = 'number';
    budget.min = '50';
    budget.step = '25';
    budget.value = String(loadSetting('mts.tradeBudget', 300));
    budget.title = 'Maximum debit for one options setup';
    budget.style.width = '88px';
    budget.style.marginLeft = '6px';

    const maxContracts = document.createElement('input');
    maxContracts.id = 'maxContracts';
    maxContracts.type = 'number';
    maxContracts.min = '1';
    maxContracts.max = '20';
    maxContracts.step = '1';
    maxContracts.value = String(loadSetting('mts.maxContracts', 3));
    maxContracts.title = 'Maximum contracts allowed for one setup';
    maxContracts.style.width = '58px';

    const budgetLabel = document.createElement('span');
    budgetLabel.className = 'muted';
    budgetLabel.textContent = 'Budget $';
    budgetLabel.style.marginLeft = '8px';

    const contractLabel = document.createElement('span');
    contractLabel.className = 'muted';
    contractLabel.textContent = 'Max qty';

    const button = document.createElement('button');
    button.id = 'runFusion';
    button.type = 'button';
    button.className = 'ghost-button';
    button.textContent = 'Evaluate setup';

    controls.append(budgetLabel, budget, contractLabel, maxContracts, button);

    budget.addEventListener('change', () => localStorage.setItem('mts.tradeBudget', budget.value));
    maxContracts.addEventListener('change', () => localStorage.setItem('mts.maxContracts', maxContracts.value));

    let host = document.getElementById('fusionResults');
    if (!host) {
      host = document.createElement('div');
      host.id = 'fusionResults';
      host.className = 'empty-state';
      host.textContent = 'Decision Engine, no-chase guard, and capital guard results will appear here.';
      optionCard.appendChild(host);
    }

    button.addEventListener('click', async () => {
      const symbol = (document.getElementById('activeSymbol')?.textContent || '').trim().toUpperCase();
      if (!symbol) return;

      const tradeBudget = Math.max(0, Number(budget.value) || 0);
      const contractCap = Math.max(1, Math.floor(Number(maxContracts.value) || 1));
      localStorage.setItem('mts.tradeBudget', String(tradeBudget));
      localStorage.setItem('mts.maxContracts', String(contractCap));

      button.disabled = true;
      button.textContent = 'Evaluating…';
      host.textContent = `${symbol}: refreshing data, running Kronos, Decision Engine, no-chase guard, and capital guard…`;

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
        const tradePlan = data.trade_plan || {};
        const options = Array.isArray(data.options) ? data.options : [];
        const chase = noChaseState(technical, tradePlan);

        let html = `<div><strong>Decision Engine: ${label}</strong></div>`;
        html += `<div class="fineprint">Technical: ${technical.signal || '—'} · Kronos: ${kronos.final_bias || '—'} · Stability: ${kronos.stability || '—'}</div>`;

        if (chase.noChase != null) {
          html += `<div class="fineprint">No-chase: ${money(chase.noChase)} · Current: ${money(chase.price)} · ${chase.blocked ? '<strong>TOO LATE / DO NOT CHASE</strong>' : 'inside chase guard'}</div>`;
        }

        if (!label.includes('CONFIRM') || label.includes('REJECT')) {
          html += '<div class="fineprint" style="margin-top:10px"><strong>NO TRADE:</strong> Decision Engine has not confirmed the setup.</div>';
        } else if (chase.blocked) {
          html += '<div class="fineprint" style="margin-top:10px"><strong>NO TRADE:</strong> Direction may be valid, but the underlying has already moved beyond the no-chase threshold. Wait for a retest/new setup.</div>';
        } else if (options.length) {
          const affordable = options
            .map(c => ({ candidate: c, debit: candidateDebit(c) }))
            .filter(x => x.debit != null && x.debit <= tradeBudget)
            .sort((a, b) => (Number(pick(b.candidate, ['score', 'total_score', 'fit_score'])) || 0) - (Number(pick(a.candidate, ['score', 'total_score', 'fit_score'])) || 0));

          if (!affordable.length) {
            html += `<div class="fineprint" style="margin-top:10px"><strong>NO TRADE — OVER BUDGET:</strong> no returned contract fits the $${tradeBudget.toFixed(0)} debit cap without dropping quality filters.</div>`;
          } else {
            const { candidate: c, debit } = affordable[0];
            const qty = Math.min(contractCap, Math.floor(tradeBudget / debit));
            const contract = pick(c, ['symbol', 'contract_symbol', 'option_symbol']) || 'Top research candidate';
            html += `<div style="margin-top:10px"><strong>${contract}</strong></div>`;
            html += `<div class="fineprint">Strike ${money(pick(c, ['strike', 'strike_price']))} · Expiry ${pick(c, ['expiration', 'expiry', 'expiration_date']) || '—'} · DTE ${pick(c, ['dte']) ?? '—'} · Bid/Ask ${money(pick(c, ['bid', 'bid_price']))}/${money(pick(c, ['ask', 'ask_price']))} · Delta ${pick(c, ['delta']) ?? '—'} · Fit ${pick(c, ['score', 'total_score', 'fit_score']) ?? '—'}</div>`;
            html += `<div class="fineprint"><strong>Capital Guard:</strong> ${qty > 0 ? `${qty} contract${qty === 1 ? '' : 's'} · estimated debit ${money(debit * qty)} · cap ${money(tradeBudget)}` : `NO TRADE — one contract costs about ${money(debit)}, above the ${money(tradeBudget)} cap.`}</div>`;
            html += '<div class="fineprint">Mechanical research fit only; no order is placed by this dashboard.</div>';
          }
        } else {
          html += '<div class="fineprint" style="margin-top:10px">No option-contract scan was produced. Exact contract selection only occurs after the existing Decision Engine returns CONFIRM.</div>';
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
