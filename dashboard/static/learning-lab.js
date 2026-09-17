(() => {
  const SNAPSHOT_URL = "/static/mnt-runtime.json";
  const POLL_MS = 30000;

  const number = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const pct = (value, digits = 1) => {
    const parsed = number(value);
    return parsed === null ? "—" : `${parsed.toFixed(digits)}%`;
  };

  const integer = (value) => {
    const parsed = number(value);
    return parsed === null ? "—" : Math.round(parsed).toLocaleString();
  };

  const signedPct = (value) => {
    const parsed = number(value);
    if (parsed === null) return "—";
    return `${parsed >= 0 ? "+" : ""}${parsed.toFixed(1)}%`;
  };

  const safeText = (value, fallback = "—") => {
    if (value === undefined || value === null || value === "") return fallback;
    return String(value);
  };

  const minutesAgo = (iso) => {
    if (!iso) return null;
    const stamp = Date.parse(iso);
    if (!Number.isFinite(stamp)) return null;
    return Math.max(0, (Date.now() - stamp) / 60000);
  };

  function workerBadge(worker) {
    const state = String(worker?.worker_state || "UNKNOWN").toUpperCase();
    const age = minutesAgo(worker?.heartbeat_at);
    if (age !== null && age > 5) return { label: `STALE ${Math.round(age)}m`, cls: "alert" };
    if (["HEALTHY", "IDLE", "MARKET_CLOSED"].includes(state)) return { label: state, cls: "healthy" };
    if (["DEGRADED", "CAUTION"].includes(state)) return { label: state, cls: "caution" };
    if (["ERROR", "FAILED", "STALE"].includes(state)) return { label: state, cls: "alert" };
    return { label: state, cls: "caution" };
  }

  function thresholdText(policy) {
    const current = number(policy?.current_min_score);
    const recommended = number(policy?.recommended_min_score);
    const resolved = integer(policy?.resolved_samples);
    const minimum = integer(policy?.minimum_samples_required);
    if (current === null) return { value: "—", note: "No live threshold data yet." };
    if (recommended === null || recommended <= current) {
      return {
        value: `${current.toFixed(0)}`,
        note: `${resolved}/${minimum} resolved samples. No stricter threshold recommended yet.`,
      };
    }
    return {
      value: `${current.toFixed(0)} → ${recommended.toFixed(0)}`,
      note: `${resolved}/${minimum} resolved samples. Recommendation is shadow-only; the live gate was not changed.`,
    };
  }

  function renderHorizon(horizon, raw) {
    const row = raw || {};
    const count = Number(row.count || 0);
    const average = number(row.average_return_pct);
    const median = number(row.median_return_pct);
    const positive = number(row.positive_rate_pct);
    const big = Number(row.gain_50pct_or_more_count || 0);
    const bad = Number(row.loss_50pct_or_worse_count || 0);
    return `
      <div class="mnt-horizon">
        <div class="mnt-horizon-title"><strong>${horizon} min</strong><span>${count} marks</span></div>
        <div class="mnt-horizon-return">${signedPct(average)}</div>
        <div class="mnt-horizon-note">Median ${signedPct(median)} · Positive ${pct(positive)} · ≥50% gains ${big} · ≤−50% losses ${bad}</div>
      </div>`;
  }

  function render(payload) {
    const shell = document.getElementById("mntLearningLab");
    if (!shell) return;

    const learning = payload?.learning || {};
    const worker = payload?.worker || {};
    const calibration = learning.signal_calibration || {};
    const ready = learning.ready_alerts || {};
    const options = learning.option_contract_returns || {};
    const policy = learning.threshold_policy || {};
    const risk = worker.session_risk || {};
    const badge = workerBadge(worker);
    const threshold = thresholdText(policy);
    const horizons = options.horizons || {};

    const optionMarks = Number(options.marks_total || 0);
    const resolvedSignals = Number(calibration.resolved || 0);
    const readyResolved = Number(ready.resolved || 0);
    const riskBlocked = Boolean(risk.entry_review_blocked);
    const scanShortlist = (worker.radar?.shortlist || []).join(", ") || "none yet";

    shell.innerHTML = `
      <div class="mnt-learning-head">
        <div>
          <div class="eyebrow">SHADOW EVIDENCE</div>
          <h2>MnT Learning Lab</h2>
          <p class="muted">What MnT is actually learning from its own signals, READY alerts, and option contracts. These are shadow results, not promises of future performance.</p>
        </div>
        <div id="mntLearningState" class="mnt-learning-state ${badge.cls}">${badge.label}</div>
      </div>

      <div class="mnt-learning-grid">
        <div class="mnt-learning-card">
          <span>Signal outcomes</span>
          <strong>${pct(calibration.target_first_win_rate_pct)}</strong>
          <small>${resolvedSignals} resolved · ${integer(calibration.pending)} pending · target-first stock outcome.</small>
        </div>
        <div class="mnt-learning-card">
          <span>READY alert outcomes</span>
          <strong>${pct(ready.target_first_win_rate_pct)}</strong>
          <small>${readyResolved} resolved from ${integer(ready.shadow_trades)} ranked READY ideas.</small>
        </div>
        <div class="mnt-learning-card">
          <span>Review score gate</span>
          <strong>${threshold.value}</strong>
          <small>${threshold.note}</small>
        </div>
        <div class="mnt-learning-card">
          <span>Option marks captured</span>
          <strong>${optionMarks.toLocaleString()}</strong>
          <small>${safeText(options.return_convention, "Entry ask → later bid")}.</small>
        </div>
      </div>

      <div class="mnt-option-performance">
        <h3>Actual option-contract shadow returns</h3>
        <p>Conservative measurement: MnT assumes entry at the surfaced ask and values the later contract at the bid, so spread friction is included.</p>
        <div class="mnt-horizon-grid">
          ${[15, 30, 60, 120].map((h) => renderHorizon(h, horizons[String(h)])).join("")}
        </div>
      </div>

      <div class="mnt-learning-risk">
        <strong>Session governor:</strong> ${riskBlocked ? "PAUSED" : "OPEN"}
        · ${safeText(risk.beginner_explanation || risk.reason, "No session-risk restriction reported.")}
        <br><span class="muted">Current Fusion shortlist: ${scanShortlist}</span>
      </div>

      <div class="mnt-learning-explain">${safeText(payload?.beginner_explanation, "MnT is still collecting evidence. Larger samples matter more than a few recent wins or losses.")}</div>

      <details class="mnt-learning-details">
        <summary>Technical learning details</summary>
        <pre>${JSON.stringify({
          threshold_policy: policy,
          layer_effectiveness: learning.layer_effectiveness || {},
          worker: worker,
          option_contract_returns: options,
        }, null, 2)}</pre>
      </details>
    `;
  }

  function renderError(message) {
    const shell = document.getElementById("mntLearningLab");
    if (!shell) return;
    shell.innerHTML = `
      <div class="mnt-learning-head">
        <div><div class="eyebrow">SHADOW EVIDENCE</div><h2>MnT Learning Lab</h2><p class="muted">${safeText(message, "Learning snapshot unavailable.")}</p></div>
        <div class="mnt-learning-state caution">WAITING</div>
      </div>`;
  }

  async function refresh() {
    try {
      const response = await fetch(`${SNAPSHOT_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      renderError(`Learning snapshot is not available yet (${error?.message || "unknown error"}). The worker creates it after its first supervisor loop.`);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    refresh();
    window.setInterval(refresh, POLL_MS);
  });
})();
