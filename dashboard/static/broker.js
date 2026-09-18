(() => {
  const $ = (id) => document.getElementById(id);
  const money = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }) : "—";
  };
  const num = (value, digits = 2) => {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits) : "—";
  };
  const pct = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(1)}%` : "—";
  };
  const dateText = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  };
  const safe = (value, fallback = "—") => value === undefined || value === null || value === "" ? fallback : String(value);

  function underlying(row) {
    const symbol = String(row?.symbol || '').trim().toUpperCase();
    if (!symbol) return '';
    return String(row?.asset_type || '').toUpperCase() === 'OPTION' ? symbol.split(/\s+/)[0] : symbol;
  }

  function openPnl(row) {
    const direct = Number(row?.unrealized_profit_loss);
    if (Number.isFinite(direct)) return direct;
    const longPnl = Number(row?.long_open_profit_loss);
    const shortPnl = Number(row?.short_open_profit_loss);
    if (Number.isFinite(longPnl) || Number.isFinite(shortPnl)) return (Number.isFinite(longPnl) ? longPnl : 0) + (Number.isFinite(shortPnl) ? shortPnl : 0);
    return null;
  }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  async function refreshStatus() {
    try {
      const status = await getJson("/api/schwab/status");
      const connected = Boolean(status.authorized && status.refresh_token_valid);
      $("connectionState").textContent = connected ? "CONNECTED" : status.configured ? "AUTH REQUIRED" : "NOT CONFIGURED";
      if (!status.configured) {
        $("connectionNote").textContent = "Add Schwab app settings to mnt.env.";
      } else if (connected && !status.accounts_enabled) {
        $("connectionNote").textContent = "Market-data analysis mode · account/position reads intentionally disabled";
      } else {
        $("connectionNote").textContent = "Schwab Market Data + account awareness";
      }
      $("accessState").textContent = status.access_token_valid ? "VALID" : connected ? "AUTO-REFRESH" : "—";
      $("accessExpiry").textContent = `Expires: ${dateText(status.access_expires_at)}`;
      $("refreshState").textContent = status.reauthorization_required ? "LOGIN DUE" : status.refresh_token_valid ? "VALID" : "—";
      $("refreshExpiry").textContent = `Refresh expires: ${dateText(status.refresh_expires_at)}`;
      $("orderState").textContent = "DISABLED";
      $("connectButton").classList.toggle("hidden", !status.configured || connected);
      return status;
    } catch (error) {
      $("connectionState").textContent = "ERROR";
      $("connectionNote").textContent = error.message;
      return null;
    }
  }

  function stateClass(state) {
    const value = String(state || '').toUpperCase();
    if (value === 'HOLD') return 'positive';
    if (value === 'TAKE_SOME_PROFIT') return 'positive';
    if (value === 'REVIEW_EXIT') return 'negative';
    if (value === 'PROTECT' || value === 'DO_NOT_ADD') return 'negative';
    return '';
  }

  function stateLabel(state) {
    return safe(state, 'REVIEW').replaceAll('_', ' ');
  }

  function renderReviews(payload) {
    if (payload.available === false) {
      $("reviewStatus").textContent = 'Not in use';
      $("positionReviews").innerHTML = `<div class="account"><p class="muted">${safe(payload.reason, 'Position management is disabled while Schwab is used for analysis only.')}</p></div>`;
      return;
    }
    const rows = payload.reviews || [];
    $("reviewStatus").textContent = rows.length
      ? `${payload.attention_count || 0} need attention · ${rows.length} positions reviewed`
      : 'No open positions to review';
    if (!rows.length) {
      $("positionReviews").innerHTML = '<div class="account"><p class="muted">No open positions were returned for review.</p></div>';
      return;
    }
    $("positionReviews").innerHTML = rows.map((row) => {
      const cls = stateClass(row.state);
      const analyze = row.underlying ? `/?symbol=${encodeURIComponent(row.underlying)}#trades` : '/';
      const openReturn = row.estimated_open_return_pct == null ? '—' : pct(row.estimated_open_return_pct);
      const technical = row.technical_direction && row.technical_direction !== 'UNKNOWN' ? row.technical_direction : 'NO CURRENT DATA';
      return `
        <article class="account">
          <div class="account-head">
            <div><h3>${safe(row.symbol)}</h3><div class="muted">${safe(row.asset_type)} · ${safe(row.exposure_direction)} exposure</div></div>
            <strong class="${cls}">${stateLabel(row.state)}</strong>
          </div>
          <div class="balances">
            <span>Open return ${openReturn}</span>
            <span>Open P/L ${money(row.open_profit_loss)}</span>
            <span>Portfolio weight ${pct(row.concentration_pct)}</span>
            <span>MnT direction ${technical}</span>
          </div>
          <p><strong>${safe(row.headline)}</strong></p>
          <p class="muted">${safe(row.explanation)}</p>
          <div class="actions"><a class="button" href="${analyze}">Open ${safe(row.underlying, 'trade')} analysis</a></div>
        </article>`;
    }).join('');
  }

  async function refreshReviews() {
    $("reviewStatus").textContent = 'Reviewing…';
    try {
      const payload = await getJson('/api/schwab/portfolio/review');
      renderReviews(payload);
    } catch (error) {
      $("reviewStatus").textContent = 'Unavailable';
      $("positionReviews").innerHTML = `<div class="account"><p class="negative">${safe(error.message)}</p></div>`;
    }
  }

  function renderPositions(payload) {
    if (payload.available === false) {
      $("positionStatus").textContent = 'Analysis-only mode';
      $("accounts").innerHTML = `<div class="account"><p class="muted">${safe(payload.reason, 'Schwab account and position access is intentionally disabled.')}</p></div>`;
      return;
    }
    const accounts = payload.accounts || [];
    if (!accounts.length) {
      $("accounts").innerHTML = '<div class="account"><p class="muted">No positions returned from Schwab.</p></div>';
      return;
    }
    $("accounts").innerHTML = accounts.map((account) => {
      const balances = account.balances || {};
      const rows = account.positions || [];
      return `
        <article class="account">
          <div class="account-head"><div><h3>${safe(account.account)}</h3><div class="muted">${safe(account.type, "Brokerage")}</div></div><div>${rows.length} positions</div></div>
          <div class="balances">
            <span>Liquidation ${money(balances.liquidation_value)}</span>
            <span>Cash ${money(balances.cash_balance)}</span>
            <span>Available ${money(balances.available_funds)}</span>
            <span>Buying power ${money(balances.buying_power)}</span>
          </div>
          <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Type</th><th>Long</th><th>Short</th><th>Avg</th><th>Market Value</th><th>Open P/L</th><th>Day P/L</th><th>Day %</th><th>MnT</th></tr></thead><tbody>
          ${rows.map((row) => {
            const pnl = Number(row.current_day_profit_loss);
            const cls = Number.isFinite(pnl) ? (pnl >= 0 ? "positive" : "negative") : "";
            const open = openPnl(row);
            const openCls = Number.isFinite(open) ? (open >= 0 ? 'positive' : 'negative') : '';
            const u = underlying(row);
            const analyze = u ? `/?symbol=${encodeURIComponent(u)}#trades` : '/';
            return `<tr><td>${safe(row.symbol)}</td><td>${safe(row.asset_type)}</td><td>${num(row.long_quantity)}</td><td>${num(row.short_quantity)}</td><td>${money(row.average_price)}</td><td>${money(row.market_value)}</td><td class="${openCls}">${money(open)}</td><td class="${cls}">${money(row.current_day_profit_loss)}</td><td class="${cls}">${pct(row.current_day_profit_loss_pct)}</td><td><a class="button" href="${analyze}">Analyze</a></td></tr>`;
          }).join("")}
          </tbody></table></div>
        </article>`;
    }).join("");
  }

  async function refreshPositions() {
    $("positionStatus").textContent = "Loading…";
    try {
      const status = await refreshStatus();
      const connected = Boolean(status?.authorized && status?.refresh_token_valid);
      if (!connected) {
        $("positionStatus").textContent = "Connect Schwab first";
        $("reviewStatus").textContent = "Connect Schwab first";
        $("accounts").innerHTML = '<div class="account"><p class="muted">MnT is waiting for Schwab OAuth authorization.</p></div>';
        $("positionReviews").innerHTML = '<div class="account"><p class="muted">Position-management guidance will appear after account access is enabled.</p></div>';
        return;
      }
      if (!status.accounts_enabled) {
        const message = 'Schwab is connected for market-data and option-chain analysis. Account balances and positions are intentionally not being requested.';
        $("positionStatus").textContent = 'Analysis-only mode';
        $("reviewStatus").textContent = 'Not in use';
        $("accounts").innerHTML = `<div class="account"><p class="muted">${message}</p></div>`;
        $("positionReviews").innerHTML = `<div class="account"><p class="muted">${message}</p></div>`;
        return;
      }
      const [payload] = await Promise.all([
        getJson("/api/schwab/positions"),
        refreshReviews(),
      ]);
      renderPositions(payload);
      $("positionStatus").textContent = `Updated ${new Date().toLocaleTimeString()}`;
    } catch (error) {
      $("positionStatus").textContent = "Error";
      $("accounts").innerHTML = `<div class="account"><p class="negative">${safe(error.message)}</p></div>`;
    }
  }

  function renderCandidates(payload) {
    const rows = payload.candidates || [];
    if (!rows.length) {
      $("candidates").innerHTML = '<p class="muted">No contracts met the budget/liquidity filters.</p>';
      return;
    }
    $("candidates").innerHTML = `<table><thead><tr><th>Contract</th><th>Strike</th><th>Expiry</th><th>Bid</th><th>Ask</th><th>Cost</th><th>Spread</th><th>Delta</th><th>Vol</th><th>OI</th><th>DTE</th><th>Score</th></tr></thead><tbody>
      ${rows.map((row) => `<tr><td>${safe(row.symbol)}</td><td>${num(row.strike)}</td><td>${safe(row.expiration)}</td><td>${money(row.bid)}</td><td>${money(row.ask)}</td><td>${money(row.estimated_cost)}</td><td>${pct(row.spread_pct)}</td><td>${num(row.delta, 3)}</td><td>${safe(row.volume)}</td><td>${safe(row.open_interest)}</td><td>${safe(row.days_to_expiration)}</td><td><strong>${num(row.score, 1)}</strong></td></tr>`).join("")}
    </tbody></table>`;
  }

  async function scanCandidates(event) {
    event.preventDefault();
    const symbol = $("symbol").value.trim().toUpperCase();
    const direction = $("direction").value;
    const style = $("style").value;
    const budget = Number($("budget").value || 300);
    $("candidateStatus").textContent = "Scanning Schwab option chain…";
    $("candidates").innerHTML = "";
    try {
      const params = new URLSearchParams({ direction, style, max_contract_cost: String(budget), limit: "5" });
      const payload = await getJson(`/api/schwab/options/${encodeURIComponent(symbol)}/candidates?${params}`);
      renderCandidates(payload);
      $("candidateStatus").textContent = `${payload.candidate_count || 0} candidates · ${payload.provider || "schwab"} · analysis only · no order submission`;
    } catch (error) {
      $("candidateStatus").textContent = error.message;
      $("candidates").innerHTML = "";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("refreshPositions").addEventListener("click", refreshPositions);
    $("candidateForm").addEventListener("submit", scanCandidates);
    refreshPositions();
  });
})();
