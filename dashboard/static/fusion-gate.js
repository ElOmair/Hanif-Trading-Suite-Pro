(() => {
  const analysisCard = document.querySelector('.analysis-card');
  if (!analysisCard || document.getElementById('tradeGate')) return;

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

  const watchIds = ['direction', 'kronosBias', 'kronosAction', 'kronosStability'];
  for (const id of watchIds) {
    const el = document.getElementById(id);
    if (el) new MutationObserver(render).observe(el, { childList: true, subtree: true, characterData: true });
  }

  render();
})();
