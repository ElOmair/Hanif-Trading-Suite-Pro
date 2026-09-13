(() => {
  function sideFromDirection(direction) {
    const value = String(direction || '').trim().toUpperCase();
    if (value === 'LONG') return { side: 'CALL', label: 'CALL bias' };
    if (value === 'SHORT') return { side: 'PUT', label: 'PUT bias' };
    return { side: 'WAIT', label: 'No option bias' };
  }

  function currentDirection() {
    return document.getElementById('direction')?.textContent || '';
  }

  function syncOptionSide() {
    const bias = sideFromDirection(currentDirection());
    const optionSide = document.getElementById('optionSide');
    const banner = document.getElementById('optionBiasBanner');
    const optionHint = document.getElementById('optionBiasHint');

    if (optionSide) optionSide.textContent = bias.side;
    if (banner) {
      banner.textContent = bias.side === 'WAIT'
        ? 'OPTION SIDE: WAIT'
        : `OPTION SIDE: ${bias.side}`;
      banner.dataset.side = bias.side.toLowerCase();
    }
    if (optionHint) {
      optionHint.textContent = bias.side === 'WAIT'
        ? 'No directional option bias yet.'
        : `${bias.side} bias — waiting for Kronos confirmation and the option selector to choose strike, expiration, and contract.`;
    }
  }

  const direction = document.getElementById('direction');
  if (direction) {
    new MutationObserver(syncOptionSide).observe(direction, { childList: true, characterData: true, subtree: true });
  }

  const setupDirection = document.getElementById('setupDirection');
  if (setupDirection) {
    new MutationObserver(syncOptionSide).observe(setupDirection, { childList: true, characterData: true, subtree: true });
  }

  const toastStack = document.getElementById('toastStack');
  if (toastStack) {
    new MutationObserver(mutations => {
      const bias = sideFromDirection(currentDirection());
      if (bias.side === 'WAIT') return;
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof HTMLElement) || !node.classList.contains('trade-toast')) continue;
          if (node.querySelector('.option-side-line')) continue;
          const line = document.createElement('div');
          line.className = 'option-side-line';
          line.textContent = `Option side: ${bias.side}`;
          node.appendChild(line);
        }
      }
    }).observe(toastStack, { childList: true });
  }

  syncOptionSide();
})();
