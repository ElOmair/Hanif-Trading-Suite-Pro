(() => {
  const analysisCard = document.querySelector('.analysis-card');
  if (!analysisCard || document.getElementById('tradeGate')) return;

  let latestServerGate = null;

  const gate = document.createElement('div');
  gate.id = 'tradeGate';
  gate.className = 'trade-gate waiting';
  gate.innerHTML = `
    <div class="trade-gate-top">
      <span class="trade-gate-label">TRADE GATE</span>
      <strong id="tradeGateState">WAITING FOR KRONOS</strong>
    </div>
    <div id="tradeGateSummary" class="trade-gate-summary">Technical setup is not actionable until Kronos has been run.</div>
  `;

  const controls = document.querySelector('.kronos-live-controls');
  if (controls) controls.insertAdjacentElement('afterend', gate);
  else analysisCard.querySelector('h2')?.insertAdjacentElement('afterend', gate);

  const optionCard = document.querySelector('.options-card');
  if (optionCard && !document.getElementById('optionGateStatus')) {
    const box = document.createElement('div');
    box.id = 'optionGateStatus';
    box.className = 'option-gate-status waiting';
    box.textContent = 'Option selection locked until Technical + Kronos align.';
    optionCard.querySelector('h2')?.insertAdjacentElement('afterend', box);
  }

  function text(id) {
    return (document.getElementById(id)?.textContent || '').trim().toUpperCase();
  }

  function technicalSide() {
    const direction = text('direction');
    if (direction === 'LONG') return { direction, option: 'CALL', kronosBias: 'BULLISH' };
    if (direction === 'SHORT') return { direction, option: 'PUT', kronosBias: 'BEARISH' };
    return { direction: 'NEUTRAL', option: 'WAIT', kronosBias: 'NEUTRAL' };
  }

  function expiryText(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return ` Re-analyze after ${date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} if you still want the setup.`;
  }

  function renderServerGate(stateEl, summaryEl, optionStatus, setupNote) {
    const server = latestServerGate;
    if (!server || !server.state) return false;

    const state = String(server.state).toUpperCase();
    const direction = String(server.direction || 'NEUTRAL').toUpperCase();
    const option = direction === 'LONG' ? 'CALL' : direction === 'SHORT' ? 'PUT' : 'OPTION';
    const reason = server.primary_reason || 'MnT is waiting for the setup to pass its server-side risk gates.';
    const expiry = expiryText(server.expires_at);
    const blockerCodes = Array.isArray(server.blockers) ? server.blockers.map(item => item.code) : [];

    if (state === 'REVIEW_ENTRY' && server.entry_review_allowed === true) {
      gate.className = 'trade-gate aligned';
      stateEl.textContent = 'MNT GATES PASSED — REVIEW ENTRY';
      summaryEl.textContent = `${reason}${expiry} This is still research-only; no brokerage order is authorized.`;
      if (optionStatus) {
        optionStatus.className = 'option-gate-status aligned';
        optionStatus.textContent = `${option} setup passed the current MnT review gates. Confirm price, contract debit, stop, and no-chase level before acting.`;
      }
      if (setupNote) setupNote.textContent = `${option} setup passed the server-side review gates. order_authorized remains false.`;
      return true;
    }

    if (state === 'BLOCKED') {
      gate.className = blockerCodes.includes('DECISION_REJECT') ? 'trade-gate rejected' : 'trade-gate blocked';
      if (blockerCodes.includes('NO_CHASE')) stateEl.textContent = 'BLOCKED — DO NOT CHASE';
      else if (blockerCodes.includes('LOW_COVERAGE')) stateEl.textContent = 'BLOCKED — NOT ENOUGH DATA';
      else if (blockerCodes.includes('LOW_SCORE')) stateEl.textContent = 'BLOCKED — QUALITY SCORE TOO LOW';
      else if (blockerCodes.includes('OPENING_LOCKOUT')) stateEl.textContent = 'BLOCKED — OPENING LOCKOUT';
      else if (blockerCodes.includes('DECISION_REJECT')) stateEl.textContent = 'REJECTED BY MNT';
      else stateEl.textContent = 'BLOCKED BY MNT RISK GATE';
      summaryEl.textContent = `${reason}${expiry}`;
      if (optionStatus) {
        optionStatus.className = 'option-gate-status blocked';
        optionStatus.textContent = `${option} entry review is locked until a new Fusion analysis clears the server-side blockers.`;
      }
      if (setupNote) setupNote.textContent = `Server risk gate blocked this setup: ${blockerCodes.join(', ') || 'risk check failed'}.`;
      return true;
    }

    gate.className = 'trade-gate waiting';
    stateEl.textContent = 'WAIT — MNT NEEDS CONFIRMATION';
    summaryEl.textContent = `${reason}${expiry}`;
    if (optionStatus) {
      optionStatus.className = 'option-gate-status waiting';
      optionStatus.textContent = `${option} entry review stays locked until the server-side Decision/Risk gates confirm it.`;
    }
    if (setupNote) setupNote.textContent = 'MnT server gate is waiting. Do not enter early.';
    return true;
  }

  function render() {
    const side = technicalSide();
    const bias = text('kronosBias');
    const action = text('kronosAction');
    const stability = text('kronosStability');
    const stateEl = document.getElementById('tradeGateState');
    const summaryEl = document.getElementById('tradeGateSummary');
    const optionStatus = document.getElementById('optionGateStatus');
    const setupNote = document.getElementById('setupNote');

    gate.className = 'trade-gate waiting';
    if (optionStatus) optionStatus.className = 'option-gate-status waiting';

    // Once a Fusion payload exists, the backend risk governor is authoritative.
    if (renderServerGate(stateEl, summaryEl, optionStatus, setupNote)) return;

    if (!bias || bias === '—' || bias === 'CHECKING' || bias === 'RUNNING…') {
      stateEl.textContent = 'WAITING FOR KRONOS';
      summaryEl.textContent = side.option === 'WAIT'
        ? 'No technical direction yet.'
        : `Technical bias is ${side.direction} / ${side.option}, but this is not a trade until Kronos confirms it.`;
      if (optionStatus) optionStatus.textContent = 'Option selection locked until Technical + Kronos align.';
      return;
    }

    if (side.option === 'WAIT') {
      stateEl.textContent = 'NO TRADE — NO TECHNICAL DIRECTION';
      summaryEl.textContent = `Kronos is ${bias}, but the technical layer is neutral. Wait for a valid setup.`;
      if (optionStatus) optionStatus.textContent = 'No option selected.';
      if (setupNote) setupNote.textContent = 'No actionable setup. Technical direction is neutral.';
      return;
    }

    if (bias === 'NEUTRAL' || action === 'WAIT') {
      gate.className = 'trade-gate blocked';
      stateEl.textContent = 'NO TRADE — KRONOS NOT CONFIRMING';
      summaryEl.textContent = `Technicals say ${side.direction} / ${side.option}, but Kronos is ${bias}${stability ? ` with ${stability} stability` : ''} and action ${action || 'WAIT'}. Do not buy the ${side.option} yet.`;
      if (optionStatus) {
        optionStatus.className = 'option-gate-status blocked';
        optionStatus.textContent = `${side.option} bias exists technically, but option selection is locked because Kronos has not confirmed the direction.`;
      }
      if (setupNote) setupNote.textContent = `Technical preview only. Kronos has not confirmed this ${side.option} setup — no trade.`;
      return;
    }

    if (bias !== side.kronosBias) {
      gate.className = 'trade-gate rejected';
      stateEl.textContent = 'REJECTED — KRONOS OPPOSES TECHNICALS';
      summaryEl.textContent = `Technicals say ${side.direction} / ${side.option}, while Kronos is ${bias}. Stand down and wait for a new setup.`;
      if (optionStatus) {
        optionStatus.className = 'option-gate-status rejected';
        optionStatus.textContent = 'No option selected because the model and technical direction disagree.';
      }
      if (setupNote) setupNote.textContent = 'Setup rejected because Kronos opposes the technical direction.';
      return;
    }

    gate.className = 'trade-gate aligned';
    stateEl.textContent = 'ALIGNED — READY FOR DECISION ENGINE';
    summaryEl.textContent = `Technicals and Kronos both support ${side.direction} / ${side.option}. Next gate: decision engine, no-chase/capital rules, then exact contract selection.`;
    if (optionStatus) {
      optionStatus.className = 'option-gate-status aligned';
      optionStatus.textContent = `${side.option} direction aligned. Exact strike/expiration still requires the option selector and risk gates.`;
    }
    if (setupNote) setupNote.textContent = `Technical + Kronos direction aligned for ${side.option}. Not final CONFIRM until the decision/risk gates pass.`;
  }

  window.addEventListener('mnt:fusion-result', event => {
    latestServerGate = event.detail?.execution_gate || null;
    render();
  });

  const watchIds = ['direction', 'kronosBias', 'kronosAction', 'kronosStability'];
  for (const id of watchIds) {
    const el = document.getElementById(id);
    if (el) new MutationObserver(render).observe(el, { childList: true, subtree: true, characterData: true });
  }

  render();
})();
