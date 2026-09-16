(() => {
  const originalFetch = window.fetch.bind(window);
  const number = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const money = value => number(value) == null ? '—' : `$${number(value).toFixed(2)}`;

  function pick(obj, keys) {
    if (!obj || typeof obj !== 'object') return undefined;
    for (const key of keys) if (obj[key] !== undefined && obj[key] !== null && obj[key] !== '') return obj[key];
    return undefined;
  }

  function labelDecision(decision) {
    if (!decision) return 'UNKNOWN';
    if (typeof decision === 'string') return decision.toUpperCase();
    return String(pick(decision, ['decision', 'action', 'state', 'status']) || 'UNKNOWN').toUpperCase();
  }

  function candidateDebit(candidate) {
    const ask = number(pick(candidate, ['ask', 'ask_price']));
    const bid = number(pick(candidate, ['bid', 'bid_price']));
    if (ask != null && ask > 0) return ask * 100;
    if (ask != null && bid != null && ask > 0 && bid > 0) return ((ask + bid) / 2) * 100;
    return null;
  }

  function noChase(technical, tradePlan) {
    const direction = String(technical?.signal || '').toUpperCase();
    const price = number(technical?.price);
    const atr = number(technical?.atr);
    const low = number(pick(tradePlan, ['entry_low', 'entryLow'])) ?? number(technical?.entry_low);
    const high = number(pick(tradePlan, ['entry_high', 'entryHigh'])) ?? number(technical?.entry_high);
    let limit = number(pick(tradePlan, ['no_chase', 'no_chase_price', 'chase_limit', 'chaseLimit']));
    if (limit == null && atr != null) {
      if (direction === 'LONG' && high != null) limit = high + atr * 0.25;
      if (direction === 'SHORT' && low != null) limit = low - atr * 0.25;
    }
    const blocked = price != null && limit != null && (direction === 'LONG' ? price > limit : direction === 'SHORT' ? price < limit : false);
    return { direction, price, low, high, limit, blocked };
  }

  function ensureCoach() {
    let host = document.getElementById('mntBeginnerCoach');
    if (host) return host;
    const card = document.querySelector('.analysis-card');
    if (!card) return null;
    host = document.createElement('section');
    host.id = 'mntBeginnerCoach';
    host.className = 'mnt-coach';
    host.innerHTML = `
      <div class="mnt-coach-head">
        <div><div class="eyebrow">MNT BEGINNER COACH</div><h3>What should I do?</h3></div>
        <span id="mntCoachState" class="mnt-coach-state wait">WAITING</span>
      </div>
      <div id="mntScoreStrip" class="mnt-score-strip" aria-live="polite">
        <div class="mnt-score-box"><span class="mnt-score-label">MnT score</span><strong id="mntScoreValue">—</strong><span>/100</span></div>
        <div class="mnt-score-box"><span class="mnt-score-label">Data coverage</span><strong id="mntCoverageValue">—</strong><span>%</span></div>
        <div class="mnt-score-box wide"><span class="mnt-score-label">Quality</span><strong id="mntGradeValue">WAITING</strong></div>
      </div>
      <div id="mntCoverageNote" class="mnt-coverage-note">MnT will show which professional data layers were actually available for this setup.</div>
      <div id="mntCoachAction" class="mnt-coach-action">Run “Analyze Trade Setup” and MnT will explain the result in plain English.</div>
      <ol id="mntCoachSteps" class="mnt-coach-steps"></ol>
      <div id="mntCoachWhy" class="mnt-coach-why"></div>
    `;
    card.appendChild(host);
    return host;
  }

  function technicalChecks(technical, kronos) {
    const checks = [];
    const signal = String(technical?.signal || '').toUpperCase();
    const vwap = String(technical?.vwap || '').toLowerCase();
    const bos = String(technical?.bos || '').toLowerCase();
    const choch = String(technical?.choch || '').toLowerCase();
    const rvol = number(technical?.rvol);
    const finalBias = String(kronos?.final_bias || '').toUpperCase();

    if (signal === 'LONG') checks.push('✅ Short-term price action currently favors buyers.');
    if (signal === 'SHORT') checks.push('✅ Short-term price action currently favors sellers.');
    if (signal === 'NEUTRAL') checks.push('⚠️ Price action is mixed. MnT does not see a clear short-term edge yet.');

    if (vwap === 'bullish') checks.push('✅ Price is above today’s average trading price, which usually means buyers have more control.');
    if (vwap === 'bearish') checks.push('⚠️ Price is below today’s average trading price, so sellers still have some control.');

    if (bos === 'bullish') checks.push('✅ Price pushed above a recent high. That is a sign of strength.');
    if (bos === 'bearish') checks.push('✅ Price pushed below a recent low. That is a sign of weakness.');
    if (choch === 'bullish') checks.push('✅ Recent momentum shifted toward buyers.');
    if (choch === 'bearish') checks.push('✅ Recent momentum shifted toward sellers.');

    if (rvol != null && rvol >= 1.3) checks.push(`✅ Trading activity is strong at about ${rvol.toFixed(2)}× normal volume.`);
    else if (rvol != null) checks.push(`ℹ️ Trading activity is about ${rvol.toFixed(2)}× normal volume.`);

    if (finalBias && signal && signal !== 'NEUTRAL') {
      const agrees = (signal === 'LONG' && finalBias === 'BULLISH') || (signal === 'SHORT' && finalBias === 'BEARISH');
      checks.push(agrees ? '✅ Kronos agrees with the short-term direction.' : '⚠️ Kronos and the short-term chart do not fully agree yet.');
    }
    return checks.slice(0, 6);
  }

  function gammaExplanation(data) {
    const gamma = data?.gamma;
    if (!gamma || gamma.available === false || gamma.status === 'not_configured') {
      return '<div class="mnt-layer-note"><strong>Gamma:</strong> unavailable for this result. MnT removed its gamma weight instead of scoring missing data as bearish.</div>';
    }

    const regime = String(gamma.regime || gamma.gamma_regime || '').toUpperCase();
    const zero = number(gamma.zero_gamma ?? gamma.gamma_flip);
    const callWall = number(gamma.call_wall);
    const putWall = number(gamma.put_wall);
    let simple = 'Gamma is connected, but the current dealer pressure is mixed.';
    if (regime.includes('NEGATIVE') || regime.includes('EXPANSION')) simple = 'Dealer hedging may help price move faster than normal, so breakouts and breakdowns can accelerate.';
    if (regime.includes('POSITIVE') || regime.includes('PIN')) simple = 'Dealer hedging may slow price down and keep it trapped near important strikes.';
    return `<div class="mnt-layer-note"><strong>Gamma:</strong> ${simple}${zero != null ? ` Flip ${money(zero)}.` : ''}${callWall != null ? ` Call wall ${money(callWall)}.` : ''}${putWall != null ? ` Put wall ${money(putWall)}.` : ''}</div>`;
  }

  function flowExplanation(data) {
    const flow = data?.flow;
    if (!flow || flow.available === false) {
      const reason = flow?.reason ? ` ${flow.reason}` : '';
      return `<div class="mnt-layer-note"><strong>Options flow:</strong> unavailable for this result. MnT removed the flow weight rather than guessing.${reason}</div>`;
    }
    const sentiment = String(flow.sentiment || 'NEUTRAL').toUpperCase();
    const ratio = number(flow.directional_ratio);
    const bullish = number(flow.bullish_premium);
    const bearish = number(flow.bearish_premium);
    const simple = flow.beginner_explanation || (sentiment === 'BULLISH'
      ? 'Options activity is leaning bullish.'
      : sentiment === 'BEARISH'
        ? 'Options activity is leaning bearish.'
        : 'Options activity is mixed.');
    return `<div class="mnt-layer-note"><strong>Options flow:</strong> ${simple}${ratio != null ? ` Directional reading ${ratio > 0 ? '+' : ''}${ratio.toFixed(2)}.` : ''}${bullish != null && bearish != null ? ` Bullish premium ${money(bullish)} vs bearish premium ${money(bearish)}.` : ''}</div>`;
  }

  function marketExplanation(data) {
    const market = data?.market_regime;
    if (!market || market.available === false) return '';
    return `<div class="mnt-layer-note"><strong>Broader market:</strong> ${market.beginner_explanation || `Current market bias is ${String(market.sentiment || 'mixed').toLowerCase()}.`}</div>`;
  }

  function renderScore(scoreData) {
    const score = number(scoreData?.score);
    const coverage = number(scoreData?.coverage_pct);
    const grade = String(scoreData?.grade || 'UNKNOWN').replaceAll('_', ' ');
    const missing = Array.isArray(scoreData?.missing_layers) ? scoreData.missing_layers : [];
    const scoreEl = document.getElementById('mntScoreValue');
    const coverageEl = document.getElementById('mntCoverageValue');
    const gradeEl = document.getElementById('mntGradeValue');
    const noteEl = document.getElementById('mntCoverageNote');
    if (scoreEl) scoreEl.textContent = score == null ? '—' : score.toFixed(0);
    if (coverageEl) coverageEl.textContent = coverage == null ? '—' : coverage.toFixed(0);
    if (gradeEl) gradeEl.textContent = grade;
    if (noteEl) {
      if (coverage == null) noteEl.textContent = 'No coverage calculation was returned.';
      else if (!missing.length) noteEl.textContent = `All MnT scoring layers used in this setup were available. Coverage: ${coverage.toFixed(0)}%.`;
      else noteEl.textContent = `Coverage ${coverage.toFixed(0)}%. Missing/reweighted layers: ${missing.join(', ')}. Missing data is not scored as zero.`;
      noteEl.className = `mnt-coverage-note ${coverage != null && coverage < 50 ? 'low' : coverage != null && coverage >= 80 ? 'high' : ''}`;
    }
  }

  function render(data) {
    const host = ensureCoach();
    if (!host) return;
    const stateEl = document.getElementById('mntCoachState');
    const actionEl = document.getElementById('mntCoachAction');
    const stepsEl = document.getElementById('mntCoachSteps');
    const whyEl = document.getElementById('mntCoachWhy');

    const technical = data.technical || {};
    const kronos = data.kronos || {};
    const fusionScore = data.fusion_score || {};
    const tradePlan = data.trade_plan || {};
    const options = Array.isArray(data.options) ? data.options : [];
    const gate = data.market_gate || {};
    const decision = labelDecision(data.decision);
    const chase = noChase(technical, tradePlan);
    const directionWord = chase.direction === 'LONG' ? 'higher' : chase.direction === 'SHORT' ? 'lower' : 'either direction';
    const mntScore = number(fusionScore.score);
    const coverage = number(fusionScore.coverage_pct);

    renderScore(fusionScore);

    let stateText = 'KEEP AN EYE ON THIS';
    let stateClass = 'wait';
    let action = 'MnT does not have a clean entry yet. Waiting is better than forcing a trade.';
    const steps = [];

    if (gate.active) {
      stateText = 'WAIT — OPENING IS NOISY';
      action = 'Do not enter yet. The first five minutes after the market opens can move very fast and give false signals.';
      steps.push('Wait until after 9:35 ET so the first five-minute candle can finish.');
      steps.push('Run the setup again after the opening lockout ends.');
    } else if (coverage != null && coverage < 45) {
      stateText = 'WAIT — NOT ENOUGH DATA';
      action = 'The setup may look interesting, but too many MnT data layers are missing to treat the score as reliable.';
      steps.push('Do not use the score by itself. Recheck when more market, Gamma, flow, or contract data is available.');
    } else if (decision.includes('REJECT')) {
      stateText = 'SKIP THIS TRADE';
      stateClass = 'stop';
      action = 'The setup does not pass MnT’s safety checks right now.';
      steps.push('Do not try to make the trade fit. Move on and wait for another setup.');
      steps.push('Recheck later only if price structure changes and MnT produces a new setup.');
    } else if (mntScore != null && mntScore < 62) {
      stateText = 'WAIT — TOO MANY CONFLICTS';
      stateClass = 'stop';
      action = `The Decision Engine may see part of a setup, but the full MnT quality score is only ${mntScore.toFixed(0)}/100.`;
      steps.push('Wait for more layers to align instead of forcing an entry.');
    } else if (!decision.includes('CONFIRM')) {
      stateText = 'GET READY — DON’T BUY YET';
      action = `MnT sees a possible move ${directionWord}, but the setup has not fully confirmed.`;
      if (chase.low != null && chase.high != null) steps.push(`Watch the planned entry area around ${money(chase.low)}–${money(chase.high)}.`);
      else steps.push('Wait for the Decision Engine to confirm the setup before choosing a contract.');
      steps.push('Do not enter early just because the stock starts moving.');
    } else if (chase.blocked) {
      stateText = 'DO NOT CHASE';
      stateClass = 'stop';
      action = 'The idea may still be right, but price has already moved too far from the planned entry.';
      steps.push(`Current price is about ${money(chase.price)} and the no-chase level is ${money(chase.limit)}.`);
      steps.push('Wait for a pullback/retest or a completely new setup instead of paying up after the move.');
    } else {
      stateText = mntScore != null && mntScore >= 86 ? 'HIGH-QUALITY SETUP — REVIEW ENTRY' : 'ENTRY CONDITIONS MET';
      stateClass = 'ready';
      action = `MnT’s current checks agree enough to review a ${chase.direction === 'LONG' ? 'bullish' : 'bearish'} trade plan.`;
      if (chase.low != null && chase.high != null) steps.push(`Stay near the planned entry area: ${money(chase.low)}–${money(chase.high)}.`);
      if (chase.limit != null) steps.push(`Do not chase beyond about ${money(chase.limit)}.`);

      const stop = number(pick(tradePlan, ['stop', 'stop_price', 'stopLevel']));
      const tp1 = number(pick(tradePlan, ['tp1', 'target1', 'target_1']));
      const tp2 = number(pick(tradePlan, ['tp2', 'target2', 'target_2']));
      if (stop != null) steps.push(`Risk line: if the stock reaches about ${money(stop)}, the original trade idea is no longer behaving as expected.`);
      if (tp1 != null || tp2 != null) steps.push(`Profit areas: ${tp1 != null ? money(tp1) : '—'}${tp2 != null ? ` first, then ${money(tp2)}` : ''}.`);

      if (options.length) {
        const c = options[0];
        const contract = pick(c, ['symbol', 'contract_symbol', 'option_symbol']) || 'Top option candidate';
        const debit = candidateDebit(c);
        const strike = pick(c, ['strike', 'strike_price']);
        const expiry = pick(c, ['expiration', 'expiry', 'expiration_date']);
        steps.push(`Option to review: ${contract}${strike != null ? `, ${money(strike)} strike` : ''}${expiry ? `, expires ${expiry}` : ''}${debit != null ? `. About ${money(debit)} for one contract at the current ask` : ''}.`);
      } else {
        steps.push('No option contract is being recommended yet. MnT only scans contracts after the setup passes the Decision Engine.');
      }
    }

    stateEl.textContent = stateText;
    stateEl.className = `mnt-coach-state ${stateClass}`;
    actionEl.textContent = action;
    stepsEl.innerHTML = steps.map((step, index) => `<li class="mnt-coach-step"><span class="mnt-coach-step-number">${index + 1}</span><span>${step}</span></li>`).join('');

    const checks = technicalChecks(technical, kronos);
    whyEl.innerHTML = `
      <h4>Why MnT is saying this</h4>
      <div class="mnt-checks">${checks.map(check => `<div class="mnt-check">${check}</div>`).join('')}</div>
      ${gammaExplanation(data)}
      ${flowExplanation(data)}
      ${marketExplanation(data)}
      <div class="mnt-layer-note"><strong>Scoring rule:</strong> MnT reweights only the layers that actually returned data. The score is a setup-quality measure, not a guarantee that a trade will win.</div>
      <details class="mnt-advanced"><summary>Show professional details</summary><pre>${JSON.stringify({ fusion_score: fusionScore, technical, kronos, gamma: data.gamma, flow: data.flow, market_regime: data.market_regime, decision: data.decision, trade_plan: tradePlan }, null, 2)}</pre></details>
    `;
  }

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const input = args[0];
      const url = typeof input === 'string' ? input : input?.url || '';
      if (url.includes('/api/kronos/fusion/')) {
        const clone = response.clone();
        const data = await clone.json();
        if (response.ok) window.dispatchEvent(new CustomEvent('mnt:fusion-result', { detail: data }));
      }
    } catch (_) {
      // The trading workflow must never fail just because the teaching layer cannot render.
    }
    return response;
  };

  window.addEventListener('mnt:fusion-result', event => render(event.detail || {}));

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureCoach);
  else ensureCoach();
})();
