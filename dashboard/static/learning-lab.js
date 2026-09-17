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
    if (["HEALTHY", "IDLE", "MARKET_CLOSED", "OFF_HOURS", "RISK_PAUSED"].includes(state)) return { label: state, cls: "healthy" };
    if (["DEGRADED", "PARTIAL", "CAUTION"].includes(state)) return { label: state, cls: "caution" };
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
      return { value: `${current.toFixed(0)}`, note: `${resolved}/${minimum} resolved samples. No stricter threshold recommended yet.` };
    }
    return {
      value: `${current.toFixed(0)} → ${recommended.toFixed(0)}`,
      note: `${resolved}/${minimum} resolved samples. Recommendation is shadow-only; the live gate was not changed.`,
    };
  }

  function challengeText(challenge) {
    const status = String(challenge?.status || "COLLECTING").toUpperCase();
    const improvement = number(challenge?.holdout_improvement_pct_points);
    const baseline = number(challenge?.baseline_holdout?.win_rate_pct);
    const candidate = number(challenge?.candidate_holdout?.win_rate_pct);
    if (status === "CANDIDATE_VALIDATED" && challenge?.recommend_candidate) {
      return { value: `${pct(baseline)} → ${pct(candidate)}`, note: `Later holdout improved ${signedPct(improvement)} points. Candidate weights remain shadow-only.` };
    }
    if (status === "KEEP_CURRENT") {
      return { value: "KEEP CURRENT", note: safeText(challenge?.reason, "The candidate did not beat the current weights on later holdout signals.") };
    }
    return { value: "COLLECTING", note: safeText(challenge?.reason, "More resolved chronological signals are needed before challenging Fusion weights.") };
  }

  function edgeText(edgeSlices) {
    const supported = (edgeSlices?.best_supported_slices || []).filter((row) => String(row?.state || "").toUpperCase() === "SUPPORTED");
    if (!supported.length) {
      return {
        value: "NO CLEAR SLICE",
        note: `${integer(edgeSlices?.resolved)} resolved signals. A slice needs at least ${integer(edgeSlices?.minimum_samples_per_slice)} observations and meaningful lift before MnT calls it supported.`,
      };
    }
    const row = supported[0];
    const dimension = String(row.dimension || "slice").replaceAll("_", " ").toUpperCase();
    return {
      value: `${dimension}: ${safeText(row.value)}`,
      note: `${pct(row.win_rate_pct)} win rate · ${signedPct(row.lift_vs_all_pct_points)} pts vs all · n=${integer(row.resolved)}. Descriptive only; this does not auto-filter trades.`,
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
    const challenge = learning.weight_challenge || {};
    const edgeSlices = learning.edge_slices || {};
    const scorecard = learning.daily_scorecard || {};
    const risk = worker.session_risk || {};
    const badge = workerBadge(worker);
    const threshold = thresholdText(policy);
    const challenger = challengeText(challenge);
    const edge = edgeText(edgeSlices);
    const horizons = options.horizons || {};

    const optionMarks = Number(options.marks_total || 0);
    const resolvedSignals = Number(calibration.resolved || 0);
    const readyResolved = Number(ready.resolved || 0);
    const riskBlocked = Boolean(risk.entry_review_blocked);
    const scanShortlist = (worker.radar?.shortlist || []).join(", ") || "none yet";
    const dayMarks = scorecard.option_marks || {};
    const evidence = scorecard.option_evidence || {};
    const evidenceLabel = evidence.eligible_trades === undefined
      ? "evidence coverage pending"
      : `${integer(evidence.measured_trades)}/${integer(evidence.eligible_trades)} eligible measured${evidence.complete === false ? " · PARTIAL" : ""}`;

    shell.innerHTML = `
      <div class="mnt-learning-head">
        <div>
          <div class="eyebrow">SHADOW EVIDENCE</div>
          <h2>MnT Learning Lab</h2>
          <p class="muted">What MnT is actually learning from its own signals, READY alerts, option contracts, and later unseen validation. These are shadow results, not promises of future performance.</p>
        </div>
        <div id="mntLearningState" class="mnt-learning-state ${badge.cls}">${badge.label}</div>
      </div>

      <div class="mnt-learning-grid">
        <div class="mnt-learning-card">
          <span>Today's quality</span>
          <strong>${safeText(scorecard.quality_state, "COLLECTING")}</strong>
          <small>${integer(scorecard.ready_ideas)} READY ideas · ${integer(dayMarks.count)} measured ${integer(scorecard.option_horizon_minutes)}m marks · avg ${signedPct(dayMarks.average_return_pct)} · ${evidenceLabel}.</small>
        </div>
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
          <span>Measured edge</span>
          <strong>${edge.value}</strong>
          <small>${edge.note}</small>
        </div>
        <div class="mnt-learning-card">
          <span>Review score gate</span>
          <strong>${threshold.value}</strong>
          <small>${threshold.note}</small>
        </div>
        <div class="mnt-learning-card">
          <span>Weight challenger</span>
          <strong>${challenger.value}</strong>
          <small>${challenger.note}</small>
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
        <div class="mnt-horizon-grid">${[15, 30, 60, 120].map((h) => renderHorizon(h, horizons[String(h)])).join("")}</div>
      </div>

      <div class="mnt-learning-risk">
        <strong>Session governor:</strong> ${riskBlocked ? "PAUSED" : "OPEN"}
        · ${safeText(risk.beginner_explanation || risk.reason, "No session-risk restriction reported.")}
        <br><strong>Next-session note:</strong> ${safeText(scorecard.next_session_note, "Keep collecting shadow evidence.")}
        <br><span class="muted">Current Fusion shortlist: ${scanShortlist}</span>
      </div>

      <div class="mnt-learning-explain">${safeText(payload?.beginner_explanation, "MnT is still collecting evidence. Larger samples matter more than a few recent wins or losses.")}</div>

      <details class="mnt-learning-details">
        <summary>Technical learning details</summary>
        <pre>${JSON.stringify({ daily_scorecard: scorecard, edge_slices: edgeSlices, threshold_policy: policy, weight_challenge: challenge, layer_effectiveness: learning.layer_effectiveness || {}, worker: worker, option_contract_returns: options }, null, 2)}</pre>
      </details>
    `;
  }

  function renderError(message) {
    const shell = document.getElementById("mntLearningLab");
    if (!shell) return;
    shell.innerHTML = `<div class="mnt-learning-head"><div><div class="eyebrow">SHADOW EVIDENCE</div><h2>MnT Learning Lab</h2><p class="muted">${safeText(message, "Learning snapshot unavailable.")}</p></div><div class="mnt-learning-state caution">WAITING</div></div>`;
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
