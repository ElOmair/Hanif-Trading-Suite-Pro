(() => {
  const KEY = 'mts.setupJournal.v1';

  function loadRows() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || '[]');
      return Array.isArray(value) ? value : [];
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
      <div class="fineprint" style="margin-top:10px">Local research journal only. Broker fills and live position data are not connected yet.</div>
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

    const symbol = text('activeSymbol');
    const row = {
      id: `${symbol}-${Date.now()}`,
      created_at: new Date().toISOString(),
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
    };

    const rows = loadRows();
    rows.unshift(row);
    saveRows(rows);
    note.textContent = `${symbol} confirmed setup saved locally.`;
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
      return `
        <div style="border:1px solid #1c3142;border-radius:10px;padding:10px;background:rgba(10,21,31,.55)">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:start">
            <div><strong>${row.symbol} · ${row.direction}</strong><div class="fineprint">${when} · ${row.option_side || 'WAIT'}</div></div>
            <button class="ghost-button remove-saved-setup" data-id="${row.id}" type="button">Remove</button>
          </div>
          <div class="fineprint" style="margin-top:7px">Kronos ${row.final_bias || '—'} · ${row.stability || '—'} stability · score ${row.kronos_score || '—'}</div>
          <div class="fineprint">Entry ${row.entry_zone || '—'} · No chase ${row.no_chase || '—'} · Stop ${row.stop || '—'}</div>
          <div class="fineprint">TP1 ${row.tp1 || '—'} · TP2 ${row.tp2 || '—'} · TP3 ${row.tp3 || '—'}</div>
        </div>
      `;
    }).join('');

    host.querySelectorAll('.remove-saved-setup').forEach(button => {
      button.addEventListener('click', () => {
        saveRows(loadRows().filter(row => row.id !== button.dataset.id));
        render();
      });
    });
  }

  ensureUi();
})();
