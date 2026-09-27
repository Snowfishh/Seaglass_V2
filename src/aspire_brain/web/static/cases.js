document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-case] button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var caseId = btn.closest('.panel').getAttribute('data-case');
      runCase(caseId, btn);
    });
  });
});

async function runCase(id, btn) {
  btn.disabled = true;
  var container = btn.closest('.panel').querySelector('.case-result');
  container.innerHTML = '<p class="muted">Running simulator…</p>';
  try {
    var sessionResponse = await fetch('/api/session');
    var session = await sessionResponse.json();
    if (!session.principal) {
      container.innerHTML = '<p class="muted">Choose a demo persona on the Ask page first.</p>';
      return;
    }
    var res = await fetch('/api/cases/' + id, {
      method: 'POST',
      headers: {'X-CSRF-Token': session.csrf_token},
    });
    var data = await res.json();
    if (!res.ok) {
      container.innerHTML = '<p class="muted">Error: ' + escapeHtml(data.detail || 'Unavailable') + '</p>';
      return;
    }
    renderResult(container, data);
  } catch (e) {
    container.innerHTML = '<p class="muted">Network or service error.</p>';
  } finally {
    btn.disabled = false;
  }
}

function renderResult(container, data) {
  if (data.inquiry) {
    renderInquiry(container, data);
    return;
  }
  if (data.status === 'pending') {
    container.innerHTML = '<div class="result-card"><p><strong>Status:</strong> <span class="pending-badge">Pending</span></p>' +
      '<p>' + escapeHtml(data.reason) + '</p></div>';
    return;
  }
  var packet = data.packet || {};
  var html = '<div class="result-card">';
  html += '<p><strong>Principal:</strong> ' + escapeHtml(data.principal) + '</p>';
  html += '<p><strong>Platforms:</strong> ' + escapeHtml(data.platforms.join(', ')) + '</p>';
  html += '<p><strong>Query status:</strong> <code>' + escapeHtml(packet.query_status || 'unknown') + '</code></p>';
  if (packet.routing) {
    html += '<p><strong>Routing:</strong> <code>' + escapeHtml(packet.routing.mode) + '</code> · ' +
      escapeHtml(packet.routing.selected_platforms.join(', ')) +
      ' <span class="muted">(' + escapeHtml(packet.routing.basis) + ')</span></p>';
    if (packet.routing.omitted_platforms && packet.routing.omitted_platforms.length) {
      html += '<p class="muted small">Omitted: ' +
        escapeHtml(packet.routing.omitted_platforms.join(', ')) + ' — ' +
        escapeHtml(packet.routing.coverage_note) + '</p>';
    }
  }
  if (packet.simulation_mode) {
    html += '<p><strong>Mode:</strong> <code>' + escapeHtml(packet.simulation_mode) + '</code></p>';
  }
  if (packet.source_status) {
    html += '<p><strong>Source freshness:</strong></p><ul>';
    for (var platform in packet.source_status) {
      var status = packet.source_status[platform];
      html += '<li>' + escapeHtml(platform) + ': <code>' + escapeHtml(status.freshness_state) + '</code>';
      if (status.source_failure) html += ' (failure: ' + escapeHtml(status.source_failure) + ')';
      html += '</li>';
    }
    html += '</ul>';
  }
  if (packet.incomplete_platforms && packet.incomplete_platforms.length) {
    html += '<p><strong>Incomplete platforms:</strong> ' + escapeHtml(packet.incomplete_platforms.join(', ')) + '</p>';
  }
  if (packet.context_budget) {
    var b = packet.context_budget;
    html += '<p><strong>Context budget:</strong> items ' + escapeHtml(String(b.included_items)) + '/' +
      escapeHtml(String(b.max_items)) + ' · chars ' + escapeHtml(String(b.included_chars)) + '/' +
      escapeHtml(String(b.max_chars)) + ' · dropped ' + escapeHtml(String(b.dropped_items)) +
      ' · degraded <code>' + escapeHtml(String(b.degraded)) + '</code></p>';
    if (b.budget_excluded_platforms && b.budget_excluded_platforms.length) {
      html += '<p class="muted small">Budget-excluded platforms: ' +
        escapeHtml(b.budget_excluded_platforms.join(', ')) + '</p>';
    }
  }
  if (packet.retrieval) {
    var r = packet.retrieval;
    html += '<p><strong>Retrieval cap:</strong> ' + escapeHtml(String(r.cap_per_platform)) +
      ' per platform, applied after ' + escapeHtml(r.applied_after) +
      ' · truncated <code>' + escapeHtml(String(r.any_truncated)) + '</code></p>';
    if (r.any_truncated) {
      html += '<p class="muted small">' + escapeHtml(r.note) + '</p>';
    }
  }
  var timeScope = data.time_scope || packet.time_scope;
  if (timeScope && timeScope.applied) {
    html += '<p><strong>Time scope:</strong></p><ul>';
    for (var scopePlatform in timeScope.platforms) {
      var ts = timeScope.platforms[scopePlatform];
      html += '<li>' + escapeHtml(scopePlatform) + ': <code>' + escapeHtml(ts.start) + '</code> → <code>' +
        escapeHtml(ts.end) + '</code> (basis ' + escapeHtml(ts.basis) + ')</li>';
    }
    html += '</ul>';
  }
  if (data.time_scope_note) {
    html += '<p class="muted small">' + escapeHtml(data.time_scope_note) + '</p>';
  }
  if (packet.citations && packet.citations.length) {
    html += '<p><strong>Citations:</strong></p><ul>';
    for (var i = 0; i < packet.citations.length; i++) {
      var c = packet.citations[i];
      html += '<li><code>' + escapeHtml(c.platform) + '</code> — ' + escapeHtml(c.source_id) +
        ' (' + escapeHtml(c.source_kind) + ') <span class="muted">' + escapeHtml(c.locator) + '</span></li>';
    }
    html += '</ul>';
  }
  if (data.after_packet) {
    html += '<p><strong>After revocation:</strong> saved packet access <code>' + escapeHtml(data.after_packet) + '</code></p>';
  }
  if (data.after_query) {
    html += '<p><strong>After revocation query status:</strong> <code>' + escapeHtml(data.after_query.query_status) + '</code></p>';
  }
  if (data.sync_run) {
    html += '<p><strong>Synchronization:</strong> <code>' + escapeHtml(data.sync_run.outcome) +
      '</code> · created ' + escapeHtml(String(data.sync_run.created)) +
      ' · updated ' + escapeHtml(String(data.sync_run.updated)) +
      ' · deleted ' + escapeHtml(String(data.sync_run.deleted)) +
      ' · ACL ' + escapeHtml(String(data.sync_run.acl_changes)) +
      ' · pages ' + escapeHtml(String(data.sync_run.pages_read)) + '</p>';
  }
  if (data.pre_sync_packet) {
    var platformKey = (data.platforms && data.platforms[0]) || '';
    var preStatus = (data.pre_sync_packet.source_status || {})[platformKey] || {};
    html += '<p><strong>Before sync:</strong> query status <code>' +
      escapeHtml(data.pre_sync_packet.query_status) + '</code> · freshness <code>' +
      escapeHtml(preStatus.freshness_state || 'unknown') + '</code></p>';
  }
  if (data.after_delete_query) {
    html += '<p><strong>After delete:</strong> query status <code>' +
      escapeHtml(data.after_delete_query.query_status) + '</code> · citations ' +
      escapeHtml(String((data.after_delete_query.citations || []).length)) + '</p>';
  }
  if (data.measurement) {
    html += renderMeasurement('Freshness measurement', data.measurement);
  }
  if (data.over_budget_measurement) {
    html += renderMeasurement('Over-budget comparison', data.over_budget_measurement);
  }
  if (data.provider_note) {
    html += '<p class="muted small">' + escapeHtml(data.provider_note) + '</p>';
  }
  if (data.provider_runtime) {
    html += renderProviderRuntime(data.provider_runtime);
  }
  if (data.claim_support) {
    html += renderClaimSupport('Claim-level support', data.claim_support);
  }
  if (data.default_packet) {
    html += '<p><strong>Default mode:</strong> <code>' +
      escapeHtml(data.default_packet.provider_mode || 'offline_extractive') +
      '</code> · query status <code>' + escapeHtml(data.default_packet.query_status) + '</code></p>';
  }
  if (data.abstention) {
    var ab = data.abstention.packet || {};
    var abSupport = ab.claim_support || {};
    html += '<p><strong>Abstention control:</strong> query status <code>' +
      escapeHtml(ab.query_status) + '</code> · claims asserted ' +
      escapeHtml(String(abSupport.denominator)) + ' · abstained <code>' +
      escapeHtml(String(abSupport.abstained)) + '</code></p>';
    html += '<p class="muted small">' + escapeHtml(data.abstention.query) + '</p>';
  }
  if (packet.answer) {
    html += '<p><strong>Answer:</strong></p><pre class="answer-pre">' + escapeHtml(packet.answer) + '</pre>';
  }
  if (packet.audit_event_id && packet.audit_event_id !== 'pending') {
    html += '<p class="muted small">Audit event: ' + escapeHtml(packet.audit_event_id) + '</p>';
  }
  html += '</div>';
  container.innerHTML = html;
}

function renderMeasurement(label, m) {
  var html = '<div class="measurement"><p><strong>' + escapeHtml(label) + '</strong> <code>' +
    escapeHtml(m.outcome) + '</code></p><ul>';
  html += '<li>Mutation: <code>' + escapeHtml(m.mutation_at) + '</code></li>';
  html += '<li>Ingested: <code>' + escapeHtml(m.ingested_at) + '</code></li>';
  html += '<li>Observed answer (demo query): <code>' + escapeHtml(m.observed_answer_at) + '</code></li>';
  if (m.first_post_sync_query_at) {
    html += '<li>First post-sync query (observed): <code>' + escapeHtml(m.first_post_sync_query_at) +
      '</code> · contains update <code>' + escapeHtml(String(m.first_post_sync_answer_contains_update)) +
      '</code></li>';
  }
  html += '<li class="muted small">Earliest correct answer: ' +
    (m.earliest_correct_answer_at === null || m.earliest_correct_answer_at === undefined
      ? 'unknown (not polled)' : escapeHtml(m.earliest_correct_answer_at)) +
    ' · observation mode: ' + escapeHtml(m.observation_mode || 'observed_query') + '</li>';
  html += '<li>Budget ' + escapeHtml(String(m.budget_seconds)) + ' s · propagation ' +
    escapeHtml(String(m.propagation_seconds)) + ' s · answer latency ' +
    escapeHtml(String(m.answer_latency_seconds)) + ' s</li>';
  html += '<li>Within budget: <code>' + escapeHtml(String(m.within_budget)) + '</code></li>';
  html += '<li class="muted small">Time mode: ' + escapeHtml(m.time_mode) + ' · wall-clock: ' +
    (m.wall_clock_seconds === null ? 'unmeasured' : escapeHtml(String(m.wall_clock_seconds))) +
    ' · live propagation: ' +
    (m.live_propagation_seconds === null ? 'unmeasured' : escapeHtml(String(m.live_propagation_seconds))) +
    '</li></ul></div>';
  return html;
}

function renderClaimSupport(label, report) {
  var html = '<div class="measurement"><p><strong>' + escapeHtml(label) + '</strong> · mode <code>' +
    escapeHtml(report.mode) + '</code> · provider <code>' + escapeHtml(report.provider_mode) +
    '</code> · method <code>' + escapeHtml(report.method || 'exact_cited_span') + '</code></p><ul>';
  html += '<li>Denominator: ' + escapeHtml(String(report.denominator)) + ' claims · supported ' +
    escapeHtml(String(report.supported_claims)) + ' · unsupported ' +
    escapeHtml(String(report.unsupported_claims)) + ' · all supported <code>' +
    escapeHtml(String(report.all_supported)) + '</code></li>';
  html += '<li>Abstained: <code>' + escapeHtml(String(report.abstained)) + '</code> · notices excluded ' +
    escapeHtml(String(report.notices_excluded)) +
    '</li>';
  (report.claims || []).forEach(function (claim) {
    html += '<li><code>' + escapeHtml(claim.supported ? 'supported' : 'unsupported') + '</code> (' +
      escapeHtml(claim.reason) + ', overlap ' + escapeHtml(String(claim.support_ratio)) +
      ' — diagnostic only) ' + escapeHtml(claim.claim) + '</li>';
  });
  html += '<li class="muted small">' + escapeHtml(report.limitation) + '</li></ul></div>';
  return html;
}

function renderProviderRuntime(record) {
  var html = '<div class="measurement"><p><strong>Provider runtime</strong> · mode <code>' +
    escapeHtml(record.mode) + '</code> · outcome <code>' + escapeHtml(record.outcome) +
    '</code></p><ul>';
  html += '<li>Live request made: <code>' + escapeHtml(String(record.live_request_made)) + '</code></li>';
  ['service', 'model', 'endpoint_host', 'region', 'cost_usd', 'latency_ms'].forEach(function (key) {
    html += '<li>' + escapeHtml(key) + ': ' +
      (record[key] === null || record[key] === undefined ? 'unmeasured' : escapeHtml(String(record[key]))) +
      '</li>';
  });
  html += '</ul></div>';
  return html;
}

function renderInquiry(container, data) {
  var inquiry = data.inquiry;
  var html = '<div class="result-card"><p><strong>Mode:</strong> <code>simulated</code></p>';
  html += '<p><strong>Audit chain valid:</strong> <code>' +
    escapeHtml(inquiry.integrity.chain_valid) + '</code></p>';
  html += '<p class="muted small">Only encrypted simulated case queries are covered. The audit tail remains unanchored; completeness is unproven.</p>';
  if (inquiry.retention) {
    html += '<p><strong>Retention:</strong> ';
    if (inquiry.retention.policy) {
      html += 'window ' + escapeHtml(String(inquiry.retention.policy.max_age_days)) +
        ' days · cap ' + escapeHtml(String(inquiry.retention.policy.max_entries)) + ' entries';
    } else {
      html += 'no policy declared';
    }
    html += ' · payloads removed ' + escapeHtml(String(inquiry.retention.removed_count)) + '</p>';
    html += '<p class="muted small">' + escapeHtml(inquiry.retention.note) + '</p>';
  }
  if (inquiry.checkpoint_anchoring) {
    html += '<p><strong>Checkpoint anchoring:</strong> verified through checkpoint <code>' +
      escapeHtml(String(inquiry.checkpoint_anchoring.verified_through_checkpoint)) +
      '</code> · unanchored tail events ' +
      escapeHtml(String(inquiry.checkpoint_anchoring.unanchored_tail_events)) + '</p>';
    html += '<p class="muted small">' + escapeHtml(inquiry.checkpoint_anchoring.note) + '</p>';
  }
  if (inquiry.limit !== undefined) {
    html += '<p><strong>Pagination:</strong> page size ' + escapeHtml(String(inquiry.limit)) +
      ' · returned ' + escapeHtml(String(inquiry.returned)) +
      ' · total matches ' + escapeHtml(String(inquiry.total_matches)) +
      ' · more <code>' + escapeHtml(String(inquiry.has_more)) + '</code>' +
      ' · continuation ' + (inquiry.next_cursor ? '<code>issued</code>' : '<code>none</code>') + '</p>';
  }
  if (!inquiry.entries.length) {
    html += '<p>No matching protected case activity. Run Case 2 as employee, then switch to auditor.</p>';
  }
  inquiry.entries.forEach(function (entry) {
    html += '<section><p><strong>Timestamp:</strong> ' + escapeHtml(entry.timestamp) + '</p>';
    html += '<p><strong>Exact question:</strong> ' + escapeHtml(entry.question) + '</p>';
    html += '<p><strong>Retrieved IDs:</strong> ' + escapeHtml(entry.retrieved_ids.join(', ')) + '</p>';
    html += '<p><strong>Per-document decisions:</strong></p><ul>';
    entry.decisions.forEach(function (decision) {
      html += '<li>' + escapeHtml(decision.platform + ':' + decision.source_id) +
        ' — <code>' + escapeHtml(decision.allowed ? 'allowed' : 'denied') + '</code></li>';
    });
    html += '</ul><p><strong>Final answer:</strong></p><pre class="answer-pre">' +
      escapeHtml(entry.answer) + '</pre></section>';
  });
  html += '</div>';
  container.innerHTML = html;
}

function escapeHtml(text) {
  if (text == null) return '';
  var div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}
