(() => {
  const money = value => Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : '—';

  function ensureHost() {
    const coach = document.getElementById('mntBeginnerCoach');
    if (!coach) return null;
    let host = document.getElementById('mntPortfolioCoach');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'mntPortfolioCoach';
    host.className = 'mnt-layer-note';
    host.innerHTML = '<strong>Portfolio check:</strong> waiting for a connected Schwab/thinkorswim account.';
    const why = document.getElementById('mntCoachWhy');
    coach.insertBefore(host, why || null);
    return host;
  }

  function render(context) {
    const host = ensureHost();
    if (!host || !context) return;
    const relationship = String(context.relationship || 'UNKNOWN');
    let headline = 'Portfolio check complete.';
    let guidance = context.action_note || '';

    if (relationship === 'NEW') {
      headline = 'This would be a new position.';
      guidance = `${context.action_note || ''} Buying power shown by Schwab is ${money(context.buying_power)}.`;
    } else if (relationship === 'ALREADY_EXPOSED') {
      headline = 'You already have exposure in this direction.';
      guidance = `${context.action_note || ''} MnT should not treat this like starting from zero; adding more increases concentration.`;
    } else if (relationship === 'CONFLICT') {
      headline = 'This setup conflicts with a position you already own.';
      guidance = `${context.action_note || ''} Do not add the opposite trade without deciding whether it is an intentional hedge or an exit/reversal.`;
    } else if (relationship === 'MIXED') {
      headline = 'You already have mixed exposure here.';
      guidance = `${context.action_note || ''} Review the existing positions before adding risk.`;
    }

    host.innerHTML = `<strong>Portfolio check:</strong> ${headline}<br><span>${guidance}</span><br><span>Existing ${context.symbol} exposure: ${money(context.existing_market_value)} · concentration ${Number(context.concentration_pct || 0).toFixed(1)}% · risk ${context.risk_level || '—'}.</span>`;
  }

  window.addEventListener('mnt:portfolio-context', event => render(event.detail || {}));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensureHost);
  else ensureHost();
})();
