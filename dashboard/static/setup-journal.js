(() => {
  const KEY = 'mts.setupJournal.v2';
  const LEGACY_KEY = 'mts.setupJournal.v1';

  function loadRows() {
    try {
      const current = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (Array.isArray(current)) return current;
      const legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || '[]');
      return Array.isArray(legacy) ? legacy : [];
    } catch (_) {
      return [];
    }
  }

  function saveRows(rows) {
    localStorage.setItem(KEY, JSON.stringify(rows.slice(0, 25)));
  }

  function text(id) {
    return (document.getElementById(id)?.textContent || '').trim();
  }

  function money(value) {
    const n = Number(value);
    return Number.isFinite(n) ? `$${n.toFixed(2)}` : '—';
  }

  function parseNumber(regex, source) {
    const match = source.match(regex);
    if (!match) return null;
    const n = Number(String(match[1]).replace(/,/g, ''));
    return Number.isFinite(n) ? n : null;
  }

  function parseFusionSelection() {
    const host = document.getElementById('fusionResults');
    if (!host) return {};
    const source = host.textContent || '';
    const strong = [...host.querySelectorAll('strong')]
      .map(el => (el.textContent || '').trim())
      .filter(Boolean);
    const contract = strong.find(value =>
      !/^Decision Engine:/i.test(value) &&
      !/^Capital Guard:/i.test(value) &&
      !/^NO TRADE/i.test(value) &&
      !/^OPENING CANDLE/i.test(value)
    ) || null;

    return {
      contract,
      suggested_qty: parseNumber(/Capital Guard:\s*(\d+)\s*contract/i, source),
      estimated_total_debit: parseNumber(/estimated debit\s*\$([0-9,.]+)/i, source),
      budget_cap: parseNumber(/cap\s*\$([0-9,.]+)/i, source),
      strike: parseNumber(/Strike\s*\$([0-9,.]+)/i, source),
      dte: parseNumber(/DTE\s*(\d+)/i, source),
      bid: parseNumber(/Bid\/Ask\s*\$([0-9,.]+)\s*\/\s*\$[0-9,.]+/i, source),
      ask: parseNumber(/Bid\/Ask\s*\$[0-9,.]+\s*\/\s*\$([0-9,.]+)/i, source),
      delta: parseNumber(/Delta\s*([+-]?[0-9.]+)/i, source),
      fit_score: parseNumber(/Fit\s*([0-9.]+)/i, source),
    };
  }

  function ensureUi() {
    const card = document.querySelector('.positions-card');
    if (!card || document.getElementById('setupJournalList')) return;

    card.innerHTML = `
      <div class="eyebrow">PORTFOLIO</div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <h2 style="margin:0">Tracked Setups</h2>
        <button id="saveCurrentSetup" type="button" class="ghost-button">Save confirmed setup</button>
      </div>
      <div id="setupJournalNote" class="fineprint" style="margin-top:8px">Run Analyze Trade Setup first. Only a visible CONFIRM result can be saved.</div>
      <div id="setupJournalList" style="display:grid;gap:10px;margin-top:12px"></div>
      <div class="fineprint" style="margin-top:10px">Local research journal only. Entered fills are recorded manually; no brokerage order is sent.</div>
    `;

    document.getElementById('saveCurrentSetup').addEventListener('click', saveCurrent);
    render();
  }

  function saveCurrent() {
    const fusionText = text('fusionResults');
    const note = document.getElementById('setupJournalNote');
    if (!/Decision Engine:\s*CONFIRM/i.test(fusionText)) {
      note.textContent = 'Nothing saved: the current Analyze Trade Setup result is not CONFIRM.';
      return;
    }
    if (/OPENING CANDLE LOCKOUT|NO TRADE|TOO LATE \/ DO NOT CHASE|OVER BUDGET/i.test(fusionText)) {
      note.textContent = 'Nothing saved: the current result is blocked by a safety or capital guard.';
      return;
    }

    const symbol = text('activeSymbol');
    const selection = parseFusionSelection();
    const row = {
      id: `${symbol}-${Date.now()}`,
      created_at: new Date().toISOString(),
      status: 'SETUP',
      symbol,
      direction: text('direction'),
      option_side: text('optionSide'),
      technical_score: text('technicalScore'),
      kronos_state: text('kronosAnalysisState'),
      kronos_score: text('kronosScore'),
      kronos_1h: text('kronos1h'),
      kronos_2h: text('kronos2h'),
      kronos_paths: text('kronosPaths'),
      stability: text('kronosStability'),
      final_bias: text('kronosBias'),
      entry_zone: text('entryZone'),
      no_chase: text('noChase'),
      stop: text('stopLevel'),
      tp1: text('tp1Level'),
      tp2: text('tp2Level'),
      tp3: text('tp3Level'),
      result_summary: fusionText,
      ...selection,
    };

    const rows = loadRows();
    rows.unshift(row);
    saveRows(rows);
    note.textContent = selection.contract
      ? `${symbol} setup saved with ${selection.contract} and suggested qty ${selection.suggested_qty || '—'}.`
      : `${symbol} confirmed setup saved. No exact contract was present in the current result.`;
    render();
  }

  function markEntered(id) {
    const rows = loadRows();
    const row = rows.find(item => item.id === id);
    const note = document.getElementById('setupJournalNote');
    if (!row) return;
    if (!row.contract) {
      note.textContent = 'This saved setup has no exact option contract attached, so an option fill cannot be recorded yet.';
      return;
    }

    const defaultFill = row.ask || (row.estimated_total_debit && row.suggested_qty ? row.estimated_total_debit / row.suggested_qty / 100 : '');
    const fillInput = window.prompt(
      `Actual fill price for ${row.contract} (option premium, e.g. 2.35 = $235/contract):`,
      defaultFill ? Number(defaultFill).toFixed(2) : ''
    );
    if (fillInput === null) return;
    const fillPrice = Number(fillInput);
    if (!Number.isFinite(fillPrice) || fillPrice <= 0) {
      note.textContent = 'Fill was not saved: enter a valid positive option premium.';
      return;
    }

    const qtyInput = window.prompt('Actual quantity filled:', String(row.suggested_qty || 1));
    if (qtyInput === null) return;
    const qty = Math.floor(Number(qtyInput));
    if (!Number.isFinite(qty) || qty < 1) {
      note.textContent = 'Fill was not saved: quantity must be at least 1.';
      return;
    }

    row.status = 'ENTERED';
    row.entered_at = new Date().toISOString();
    row.actual_fill_price = fillPrice;
    row.actual_qty = qty;
    row.actual_debit = fillPrice * 100 * qty;
    saveRows(rows);
    note.textContent = `${row.symbol} marked ENTERED: ${qty} × ${row.contract} @ ${money(fillPrice)} premium.`;
    render();
  }

  function render() {
    const host = document.getElementById('setupJournalList');
    if (!host) return;
    const rows = loadRows();
    if (!rows.length) {
      host.innerHTML = '<div class="empty-state">No tracked setups yet.</div>';
      return;
    }

    host.innerHTML = rows.map(row => {
      const when = new Date(row.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
      const status = row.status || 'SETUP';
      const contractLine = row.contract
        ? `<div class="fineprint"><strong>${row.contract}</strong> · strike ${money(row.strike)} · DTE ${row.dte ?? '—'} · suggested qty ${row.suggested_qty ?? '—'} · est. debit ${money(row.estimated_total_debit)}</div>`
        : '<div class="fineprint">Exact option contract not captured for this setup.</div>';
      const enteredLine = status === 'ENTERED'
        ? `<div class="fineprint"><strong>ENTERED:</strong> ${row.actual_qty} × ${row.contract} @ ${money(row.actual_fill_price)} premium · total debit ${money(row.actual_debit)}</div>`
        : '';
      const enterButton = status === 'SETUP'
        ? `<button class="ghost-button mark-entered" data-id="${row.id}" type="button">I entered this trade</button>`
        : '';

      return `
        <div style="border:1px solid #1c3142;border-radius:10px;padding:10px;background:rgba(10,21,31,.55)">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:start;flex-wrap:wrap">
            <div><strong>${row.symbol} · ${row.direction}</strong><div class="fineprint">${when} · ${row.option_side || 'WAIT'} · ${status}</div></div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">${enterButton}<button class="ghost-button remove-saved-setup" data-id="${row.id}" type="button">Remove</button></div>
          </div>
          ${contractLine}
          ${enteredLine}
          <div class="fineprint" style="margin-top:7px">Kronos ${row.final_bias || '—'} · ${row.stability || '—'} stability · score ${row.kronos_score || '—'}</div>
          <div class="fineprint">Entry ${row.entry_zone || '—'} · No chase ${row.no_chase || '—'} · Stop ${row.stop || '—'}</div>
          <div class="fineprint">TP1 ${row.tp1 || '—'} · TP2 ${row.tp2 || '—'} · TP3 ${row.tp3 || '—'}</div>
        </div>
      `;
    }).join('');

    host.querySelectorAll('.mark-entered').forEach(button => {
      button.addEventListener('click', () => markEntered(button.dataset.id));
    });

    host.querySelectorAll('.remove-saved-setup').forEach(button => {
      button.addEventListener('click', () => {
        saveRows(loadRows().filter(row => row.id !== button.dataset.id));
        render();
      });
    });
  }

  ensureUi();
})();
