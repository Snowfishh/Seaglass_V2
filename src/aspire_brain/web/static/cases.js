document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-case] button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var caseId = btn.closest('.panel').getAttribute('data-case');
      runCase(caseId, btn);
    });
  });

  var typedForm = document.getElementById('typed-form');
  if (typedForm) {
    typedForm.addEventListener('submit', function (event) {
      event.preventDefault();
      runTypedQuery();
    });
  }
  document.querySelectorAll('.typed-example').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.getElementById('typed-question').value = btn.getAttribute('data-question');
    });
  });
  var refresh = document.getElementById('status-refresh');
  if (refresh) refresh.addEventListener('click', function () { platformRequest('GET', '/api/four-platform/status'); });
  var syncNow = document.getElementById('sync-now');
  if (syncNow) syncNow.addEventListener('click', function () { platformRequest('POST', '/api/four-platform/sync'); });
  document.querySelectorAll('.upstream-action').forEach(function (btn) {
    btn.addEventListener('click', function () {
      platformRequest('POST', '/api/four-platform/upstream-changes',
        {action: btn.getAttribute('data-action'), principal_id: 'user-a'});
    });
  });
});

// Sync status, manual sync and fixture upstream changes. Changes and syncs need the
// Fintech platform admin persona; status is open to every fintech persona.
async function platformRequest(method, path, body) {
  var container = document.getElementById('platform-status');
  container.innerHTML = '<p class="case-loading">Working…</p>';
  try {
    var session = await (await fetch('/api/session')).json();
    var options = {method: method, headers: {'X-CSRF-Token': session.csrf_token}};
    if (body) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    var res = await fetch(path, options);
    var data = await res.json();
    if (!res.ok) {
      container.innerHTML = '<p class="case-note">' + escapeHtml(data.detail || 'Unavailable') +
        (res.status === 403 ? '. Sign in as Fintech platform admin on the <a href="/ask">travel-policy page</a> to change or sync the platforms.' : '') + '</p>';
      return;
    }
    var html = '';
    if (data.changed) {
      var effect = data.action === 'revoke_restricted'
        ? 'Answers stop quoting these records now, and saved answers that cite them are closed; the index catches up at the next sync.'
        : 'It reaches answers at the next sync.';
      html += '<p><strong>Upstream change</strong> ' + escapeHtml(data.action.replace(/_/g, ' ')) + ': ' +
        escapeHtml(data.changed.join(', ') || 'nothing to change') + '. ' + effect + '</p>';
    }
    if (data.runs) {
      html += '<p><strong>Sync finished</strong> ' + data.runs.map(function (run) {
        return escapeHtml(platformName(run.platform)) + ' ' + chip(run.outcome);
      }).join(' · ') + '</p>';
    }
    container.innerHTML = html + renderPlatformStatus(data.status || data);
  } catch (e) {
    container.innerHTML = '<p class="case-note">Could not reach the demo server.</p>';
  }
}

function renderPlatformStatus(status) {
  var html = '<p class="muted small">Source <code>' + escapeHtml(status.source) + '</code> · clock ' +
    escapeHtml(String(status.clock.mode).replace(/_/g, ' ')) + ' <code>' + escapeHtml(status.clock.now) +
    '</code> · sync every ' + escapeHtml(String(status.sync_interval_seconds)) + ' s' +
    (status.next_sync_at ? ' · next at <code>' + escapeHtml(status.next_sync_at) + '</code>' : '') + '</p><ul>';
  for (var platform in status.platforms) {
    var entry = status.platforms[platform];
    html += '<li>' + escapeHtml(platformName(platform)) + ' ' + chip(entry.freshness_state) +
      ' <span class="muted">last synced ' + escapeHtml(entry.last_successful_sync || 'never') +
      ' · budget ' + escapeHtml(String(entry.freshness_budget_seconds)) + ' s · ' +
      escapeHtml(String(entry.records)) + ' records' +
      (entry.pending_upstream_changes ? ' · changes waiting for the next sync' : '') + '</span></li>';
  }
  html += '</ul>';
  if (status.measurements && status.measurements.length) {
    html += '<p><strong>Measured propagation</strong></p><ul>';
    status.measurements.slice().reverse().forEach(function (m) {
      html += '<li>' + escapeHtml(platformName(m.platform)) + ' · ' + escapeHtml(m.change) + ': visible after ' +
        escapeHtml(String(m.propagation_seconds)) + ' s of a ' + escapeHtml(String(m.budget_seconds)) +
        ' s budget ' + boolChip(m.within_budget, true) + ' <span class="muted">(' + escapeHtml(m.basis.replace(/_/g, ' ')) + ')</span></li>';
    });
    html += '</ul>';
  }
  return html + '<p class="muted small">' + escapeHtml(status.note) + '</p>';
}

async function reopenPacket(requestId, target) {
  target.innerHTML = '<p class="case-loading">Checking the sources again…</p>';
  try {
    var res = await fetch('/api/four-platform/packets/' + encodeURIComponent(requestId));
    var data = await res.json();
    target.innerHTML = res.ok
      ? '<p>' + chip('allowed') + ' The saved answer is still available: every cited source is still readable and unchanged.</p>'
      : '<p>' + chip('denied') + ' ' + escapeHtml(data.detail || 'Unavailable') +
        '. A cited source is no longer readable or has changed, so the saved answer is closed.</p>';
  } catch (e) {
    target.innerHTML = '<p class="case-note">Could not reach the demo server.</p>';
  }
}

async function runTypedQuery() {
  var btn = document.getElementById('typed-submit');
  var container = document.getElementById('typed-result');
  var question = document.getElementById('typed-question').value.trim();
  if (!question) {
    container.innerHTML = '<p class="case-note">Type a question first.</p>';
    return;
  }
  btn.disabled = true;
  container.innerHTML = '<p class="case-loading">Searching the four platforms…</p>';
  try {
    var sessionResponse = await fetch('/api/session');
    var session = await sessionResponse.json();
    if (!session.principal) {
      container.innerHTML = '<p class="case-note">Pick a persona on the <a href="/ask">travel-policy page</a> first.</p>';
      return;
    }
    if (session.principal.id !== 'user-a' && session.principal.id !== 'user-b') {
      container.innerHTML = '<p class="case-note">You are signed in as ' + escapeHtml(personaName(session.principal.id)) +
        ', who has no access to the fintech fixture. Switch to User A or User B on the ' +
        '<a href="/ask">travel-policy page</a>.</p>';
      return;
    }
    var res = await fetch('/api/four-platform/queries', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token},
      body: JSON.stringify({question: question}),
    });
    var data = await res.json();
    if (!res.ok) {
      container.innerHTML = '<p class="case-note">Error: ' + escapeHtml(data.detail || 'Unavailable') + '</p>';
      return;
    }
    renderResult(container, data);
    var requestId = data.packet && data.packet.request_id;
    if (requestId && data.packet.citations && data.packet.citations.length) {
      var wrap = document.createElement('div');
      wrap.className = 'result-section';
      wrap.innerHTML = '<button type="button" class="button--ghost">Re-open this saved answer</button><div aria-live="polite"></div>';
      wrap.querySelector('button').addEventListener('click', function () {
        reopenPacket(requestId, wrap.querySelector('div'));
      });
      container.querySelector('.result-card').appendChild(wrap);
    }
    if (data.freshness) document.getElementById('platform-status').innerHTML = renderPlatformStatus(data.freshness);
  } catch (e) {
    container.innerHTML = '<p class="case-note">Could not reach the demo server. Check that it is still running.</p>';
  } finally {
    btn.disabled = false;
  }
}

async function runCase(id, btn) {
  btn.disabled = true;
  var container = btn.closest('.panel').querySelector('.case-result');
  container.innerHTML = '<p class="case-loading">Running the case…</p>';
  try {
    var sessionResponse = await fetch('/api/session');
    var session = await sessionResponse.json();
    if (!session.principal) {
      container.innerHTML = '<p class="case-note">Pick a persona on the <a href="/ask">travel-policy page</a> first.</p>';
      return;
    }
    var res = await fetch('/api/cases/' + id, {
      method: 'POST',
      headers: {'X-CSRF-Token': session.csrf_token},
    });
    var data = await res.json();
    if (!res.ok) {
      container.innerHTML = '<p class="case-note">Error: ' + escapeHtml(data.detail || 'Unavailable') + '</p>';
      return;
    }
    renderResult(container, data);
  } catch (e) {
    container.innerHTML = '<p class="case-note">Could not reach the demo server. Check that it is still running.</p>';
  } finally {
    btn.disabled = false;
  }
}

var PERSONA_NAMES = {
  'user-a': 'User A', 'user-b': 'User B', employee: 'Employee', finance_lead: 'Finance lead',
  policy_admin: 'Policy admin', auditor: 'Auditor', other_tenant: 'Other company (tenant B)',
  disabled: 'Disabled account', fintech_auditor: 'Fintech auditor', fintech_admin: 'Fintech platform admin',
};
var PLATFORM_NAMES = {confluence: 'Confluence', jira: 'Jira', slack: 'Slack', drive: 'Google Drive'};

function personaName(id) { return PERSONA_NAMES[id] || String(id || '').replace(/_/g, ' '); }
function platformName(id) { return PLATFORM_NAMES[id] || id; }
function platformList(ids) { return (ids || []).map(platformName).join(', '); }
function kindName(kind) {
  return String(kind || '').replace(/_restricted$/, ' (restricted)').replace(/_/g, ' ');
}

// One plain sentence per outcome. The wording never says whether withheld records exist.
var STATUS_LEAD = {
  answered: 'Answered from sources you are allowed to read.',
  partial: 'Partial answer. Some platforms could not contribute, so check the sources before relying on it.',
  abstained: 'No answer. The evidence you are allowed to read does not answer this question, so nothing was released. ' +
    'This does not say whether other records exist.',
};

// The local answer is a notice followed by "Evidence (locator): text" blocks, and the live answer
// uses "From (locator): text" lines. Each block holds the quoted sentences of one source,
// separated by blank lines.
function splitAnswer(answer) {
  var parts = String(answer || '').split(/\n+(?=Evidence \(|From )/);
  var blocks = [];
  for (var i = 1; i < parts.length; i++) {
    var match = parts[i].match(/^(?:Evidence \(([^)]*)\)|From ([^ ]+)): ([\s\S]*)$/);
    if (!match) return {notice: answer, blocks: []};
    var locator = match[1] || match[2];
    var last = blocks[blocks.length - 1];
    if (last && last.locator === locator) last.text += '\n\n' + match[3];
    else blocks.push({locator: locator, text: match[3]});
  }
  return {notice: parts[0], blocks: blocks};
}

function excerpt(text, limit) {
  var flat = String(text).replace(/\s+/g, ' ').trim();
  if (flat.length <= limit) return flat;
  var cut = flat.slice(0, limit);
  return cut.slice(0, Math.max(cut.lastIndexOf(' '), limit - 40)) + '…';
}

function renderAnswerSection(data, packet) {
  var status = packet.query_status || 'unknown';
  var html = '<section class="answer-block"><div class="answer-block-head"><h3>Answer</h3>' + chip(status) + '</div>';
  html += '<p class="answer-lead">' + escapeHtml(STATUS_LEAD[status] || 'Status: ' + status) + '</p>';
  if (status === 'partial' && packet.incomplete_platforms && packet.incomplete_platforms.length) {
    html += '<p class="answer-gap">Nothing usable from: ' + escapeHtml(platformList(packet.incomplete_platforms)) + '</p>';
  }
  var parts = splitAnswer(packet.answer);
  var byLocator = {};
  (packet.citations || []).forEach(function (c) { byLocator[c.locator] = c; });
  if (parts.blocks.length) {
    parts.blocks.forEach(function (block) {
      var cited = byLocator[block.locator];
      var name = cited ? platformName(cited.platform) + ' · ' + cited.source_id : block.locator;
      var sentences = String(block.text).split(/\n\s*\n/).filter(function (t) { return t.trim(); });
      html += '<div class="evidence-item"><p class="evidence-source">' + escapeHtml(name) + '</p><ul class="evidence-quotes">';
      sentences.forEach(function (sentence) {
        html += '<li class="evidence-excerpt">' + escapeHtml(excerpt(sentence, 400)) + '</li>';
      });
      html += '</ul></div>';
    });
    html += '<p class="answer-notice">' + escapeHtml(parts.notice) + '</p>';
  } else if (packet.answer) {
    html += '<pre class="answer-pre">' + escapeHtml(packet.answer) + '</pre>';
  }
  if (data.time_scope_note) html += '<p class="answer-notice">' + escapeHtml(data.time_scope_note) + '</p>';
  if (data.provider_note) html += '<p class="answer-notice">' + escapeHtml(data.provider_note) + '</p>';
  return html + '</section>';
}

function renderSourcesSection(packet) {
  var citations = packet.citations || [];
  if (!citations.length) return '';
  var html = '<section class="result-section"><h4>Sources (' + citations.length + ')</h4><ul class="source-list">';
  citations.forEach(function (c) {
    var name = escapeHtml(c.source_id);
    // Fintech fixture records open on the Sources page; the numbered cases' fixtures do not.
    if (String(c.locator).indexOf('fixture://fintech-operations/') === 0) {
      var version = c.source_id + '@' + c.version_id;
      name = '<a href="/sources?version=' + encodeURIComponent(version) + '&amp;chunk=' +
        encodeURIComponent(c.source_id) + '">' + name + '</a>';
    }
    html += '<li><span class="source-platform">' + escapeHtml(platformName(c.platform)) + '</span> ' +
      name + ' <span class="muted">' + escapeHtml(kindName(c.source_kind)) + '</span></li>';
  });
  return html + '</ul></section>';
}

function renderCaseChecks(data) {
  var html = '';
  if (data.after_packet) {
    html += '<p><strong>Saved answer after revocation</strong> ' + chip(data.after_packet) + '</p>';
  }
  if (data.after_query) {
    html += '<p><strong>Same question after revocation</strong> ' + chip(data.after_query.query_status) + '</p>';
  }
  if (data.sync_run) {
    html += '<p><strong>Sync run</strong> ' + chip(data.sync_run.outcome) +
      ' · ' + escapeHtml(String(data.sync_run.created)) + ' created' +
      ' · ' + escapeHtml(String(data.sync_run.updated)) + ' updated' +
      ' · ' + escapeHtml(String(data.sync_run.deleted)) + ' deleted' +
      ' · ' + escapeHtml(String(data.sync_run.acl_changes)) + ' permission changes' +
      ' · ' + escapeHtml(String(data.sync_run.pages_read)) + ' pages read</p>';
  }
  if (data.pre_sync_packet) {
    var platformKey = (data.platforms && data.platforms[0]) || '';
    var preStatus = (data.pre_sync_packet.source_status || {})[platformKey] || {};
    html += '<p><strong>Asked before the sync</strong> ' + chip(data.pre_sync_packet.query_status) +
      ' · source ' + chip(preStatus.freshness_state || 'unknown') + '</p>';
  }
  if (data.after_delete_query) {
    html += '<p><strong>Asked after the file was deleted</strong> ' +
      chip(data.after_delete_query.query_status) + ' · ' +
      escapeHtml(String((data.after_delete_query.citations || []).length)) + ' sources cited</p>';
  }
  if (data.measurement) html += renderMeasurement('Freshness measurement', data.measurement);
  if (data.over_budget_measurement) html += renderMeasurement('Late sync for comparison', data.over_budget_measurement);
  if (data.claim_support) html += renderClaimSupport('Claim-by-claim support', data.claim_support);
  if (data.default_packet) {
    html += '<p><strong>Default mode for comparison</strong> <code>' +
      escapeHtml(data.default_packet.provider_mode || 'offline_extractive') + '</code> · ' +
      chip(data.default_packet.query_status) + '</p>';
  }
  if (data.abstention) {
    var ab = data.abstention.packet || {};
    var abSupport = ab.claim_support || {};
    html += '<p><strong>Control question it should refuse</strong> ' + chip(ab.query_status) +
      ' · ' + escapeHtml(String(abSupport.denominator)) + ' claims made · held back <code>' +
      escapeHtml(String(abSupport.abstained)) + '</code></p>';
    html += '<p class="muted small">' + escapeHtml(data.abstention.query) + '</p>';
  }
  return html ? '<section class="result-section"><h4>What this case checks</h4>' + html + '</section>' : '';
}

function renderTechnicalDetails(data, packet) {
  var html = '<p><strong>Persona</strong> ' + escapeHtml(personaName(data.principal)) + '</p>';
  html += '<p><strong>Platforms searched</strong> ' + escapeHtml(platformList(data.platforms)) + '</p>';
  if (packet.answer_focus) {
    var f = packet.answer_focus;
    html += '<p><strong>Question coverage</strong> ' + escapeHtml(String(f.covered_terms.length)) + ' of ' +
      escapeHtml(String(f.terms.length)) + ' terms (' + escapeHtml(f.terms.join(', ')) + ') · needed ' +
      escapeHtml(String(Math.round(f.threshold * 100))) + '% · applied <code>' + escapeHtml(String(f.applied)) + '</code></p>';
    if (f.platforms_without_relevant_evidence && f.platforms_without_relevant_evidence.length) {
      html += '<p class="muted small">Nothing relevant you may read on: ' +
        escapeHtml(platformList(f.platforms_without_relevant_evidence)) + '</p>';
    }
    if (f.upstream_verification) {
      var v = f.upstream_verification;
      // Only whether the check ran: a count of withheld sources would reveal a revocation.
      html += '<p><strong>Checked with the platforms before quoting</strong> ' + boolChip(v.performed, true) +
        (v.unverified_platforms && v.unverified_platforms.length
          ? ' <span class="muted">(could not confirm: ' + escapeHtml(platformList(v.unverified_platforms)) + ')</span>' : '') + '</p>';
    }
    html += '<p class="muted small">' + escapeHtml(f.note) + '</p>';
  }
  if (packet.routing) {
    html += '<p><strong>Routing</strong> <code>' + escapeHtml(packet.routing.mode) + '</code> · ' +
      escapeHtml(platformList(packet.routing.selected_platforms)) +
      ' <span class="muted">(' + escapeHtml(packet.routing.basis) + ')</span></p>';
    if (packet.routing.omitted_platforms && packet.routing.omitted_platforms.length) {
      html += '<p class="muted small">Not searched: ' + escapeHtml(platformList(packet.routing.omitted_platforms)) +
        '. ' + escapeHtml(packet.routing.coverage_note) + '</p>';
    }
  }
  if (packet.simulation_mode) {
    html += '<p><strong>Mode</strong> <code>' + escapeHtml(packet.simulation_mode) + '</code> · provider <code>' +
      escapeHtml(packet.provider_mode || '') + '</code></p>';
  }
  if (packet.source_status) {
    html += '<p><strong>Source freshness</strong></p><ul>';
    for (var platform in packet.source_status) {
      var status = packet.source_status[platform];
      html += '<li>' + escapeHtml(platformName(platform)) + ': ' + chip(status.freshness_state) +
        ' <span class="muted">last synced ' + escapeHtml(status.last_successful_sync || 'never') + '</span>';
      if (status.source_failure) html += ' (failure: ' + escapeHtml(status.source_failure) + ')';
      html += '</li>';
    }
    html += '</ul>';
  }
  if (packet.incomplete_platforms && packet.incomplete_platforms.length) {
    html += '<p><strong>Incomplete platforms</strong> ' + escapeHtml(platformList(packet.incomplete_platforms)) + '</p>';
  }
  if (packet.context_budget) {
    var b = packet.context_budget;
    html += '<p><strong>Context budget</strong> ' + escapeHtml(String(b.included_items)) + ' of ' +
      escapeHtml(String(b.max_items)) + ' items · ' + escapeHtml(String(b.included_chars)) + ' of ' +
      escapeHtml(String(b.max_chars)) + ' characters · ' + escapeHtml(String(b.dropped_items)) +
      ' dropped · degraded <code>' + escapeHtml(String(b.degraded)) + '</code></p>';
    if (b.budget_excluded_platforms && b.budget_excluded_platforms.length) {
      html += '<p class="muted small">Left out by the budget: ' + escapeHtml(platformList(b.budget_excluded_platforms)) + '</p>';
    }
  }
  if (packet.retrieval) {
    var r = packet.retrieval;
    html += '<p><strong>Retrieval cap</strong> ' + escapeHtml(String(r.cap_per_platform)) +
      ' per platform, applied after ' + escapeHtml(String(r.applied_after).replace(/_/g, ' ')) +
      ' · truncated <code>' + escapeHtml(String(r.any_truncated)) + '</code></p>';
    if (r.any_truncated) html += '<p class="muted small">' + escapeHtml(r.note) + '</p>';
  }
  var timeScope = data.time_scope || packet.time_scope;
  if (timeScope && timeScope.applied) {
    html += '<p><strong>Time scope</strong></p><ul>';
    for (var scopePlatform in timeScope.platforms) {
      var ts = timeScope.platforms[scopePlatform];
      html += '<li>' + escapeHtml(platformName(scopePlatform)) + ': <code>' + escapeHtml(ts.start) + '</code> to <code>' +
        escapeHtml(ts.end) + '</code> (by ' + escapeHtml(ts.basis) + ')</li>';
    }
    html += '</ul>';
  }
  if (packet.citations && packet.citations.length) {
    html += '<p><strong>Source locators</strong></p><ul>';
    packet.citations.forEach(function (c) {
      html += '<li><code>' + escapeHtml(c.source_id) + '</code> ' + escapeHtml(c.locator) + '</li>';
    });
    html += '</ul>';
  }
  if (data.provider_runtime) html += renderProviderRuntime(data.provider_runtime);
  if (packet.request_id) html += '<p><strong>Request ID</strong> <code>' + escapeHtml(packet.request_id) + '</code></p>';
  if (packet.audit_event_id && packet.audit_event_id !== 'pending') {
    html += '<p><strong>Audit event</strong> <code>' + escapeHtml(packet.audit_event_id) + '</code></p>';
  }
  return '<details class="tech-details"><summary>Technical details for reviewers: routing, freshness, budget and audit record</summary>' +
    '<div class="tech-body">' + html + '</div></details>';
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
  container.innerHTML = '<div class="result-card">' + renderAnswerSection(data, packet) +
    renderSourcesSection(packet) + renderCaseChecks(data) + renderTechnicalDetails(data, packet) + '</div>';
}

function renderMeasurement(label, m) {
  var html = '<div class="measurement"><p><strong>' + escapeHtml(label) + '</strong> ' +
    chip(m.outcome) + '</p><ul>';
  html += '<li>Source changed: <code>' + escapeHtml(m.mutation_at) + '</code></li>';
  html += '<li>Change synced into the index: <code>' + escapeHtml(m.ingested_at) + '</code></li>';
  html += '<li>Demo question asked: <code>' + escapeHtml(m.observed_answer_at) + '</code></li>';
  if (m.first_post_sync_query_at) {
    html += '<li>First question after the sync: <code>' + escapeHtml(m.first_post_sync_query_at) +
      '</code> · answer includes the change <code>' +
      escapeHtml(String(m.first_post_sync_answer_contains_update)) + '</code></li>';
  }
  html += '<li>Change reached the index after ' + escapeHtml(String(m.propagation_seconds)) +
    ' s, against a budget of ' + escapeHtml(String(m.budget_seconds)) + ' s · the demo question came ' +
    escapeHtml(String(m.answer_latency_seconds)) + ' s after the change</li>';
  html += '<li>Within budget: ' + boolChip(m.within_budget, true) + '</li>';
  html += '<li class="muted small">Earliest moment the answer was correct: ' +
    (m.earliest_correct_answer_at === null || m.earliest_correct_answer_at === undefined
      ? 'unknown, because it was not checked continuously' : escapeHtml(m.earliest_correct_answer_at)) +
    ' · observation: ' + escapeHtml(m.observation_mode || 'observed_query') + '</li>';
  html += '<li class="muted small">These are simulated times (' + escapeHtml(m.time_mode) + '). Wall-clock time: ' +
    (m.wall_clock_seconds === null ? 'not measured' : escapeHtml(String(m.wall_clock_seconds))) +
    ' · live propagation: ' +
    (m.live_propagation_seconds === null ? 'not measured' : escapeHtml(String(m.live_propagation_seconds))) +
    '</li></ul></div>';
  return html;
}

function renderClaimSupport(label, report) {
  var html = '<div class="measurement"><p><strong>' + escapeHtml(label) + '</strong> · mode <code>' +
    escapeHtml(report.mode) + '</code> · provider <code>' + escapeHtml(report.provider_mode) +
    '</code> · method <code>' + escapeHtml(report.method || 'exact_cited_span') + '</code></p><ul>';
  html += '<li>' + escapeHtml(String(report.denominator)) + ' claims checked · ' +
    escapeHtml(String(report.supported_claims)) + ' supported · ' +
    escapeHtml(String(report.unsupported_claims)) + ' unsupported · all supported ' +
    boolChip(report.all_supported, true) + '</li>';
  html += '<li>Held back: <code>' + escapeHtml(String(report.abstained)) + '</code> · notices left out of the count: ' +
    escapeHtml(String(report.notices_excluded)) + '</li>';
  (report.claims || []).forEach(function (claim) {
    html += '<li>' + chip(claim.supported ? 'supported' : 'unsupported') + ' ' + escapeHtml(claim.claim) +
      ' <span class="muted">(' + escapeHtml(claim.reason) + '; word overlap ' +
      escapeHtml(String(claim.support_ratio)) + ', shown for diagnosis only)</span></li>';
  });
  html += '<li class="muted small">' + escapeHtml(report.limitation) + '</li></ul></div>';
  return html;
}

function renderProviderRuntime(record) {
  var html = '<div class="measurement"><p><strong>Provider run</strong> · mode <code>' +
    escapeHtml(record.mode) + '</code> · outcome ' + chip(record.outcome) +
    '</p><ul>';
  html += '<li>Live request made: ' + boolChip(record.live_request_made, false) + '</li>';
  ['service', 'model', 'endpoint_host', 'region', 'cost_usd', 'latency_ms'].forEach(function (key) {
    html += '<li>' + escapeHtml(key.replace(/_/g, ' ')) + ': ' +
      (record[key] === null || record[key] === undefined ? 'not measured' : escapeHtml(String(record[key]))) +
      '</li>';
  });
  html += '</ul></div>';
  return html;
}

function renderInquiry(container, data) {
  var inquiry = data.inquiry;
  var count = inquiry.entries.length;
  var total = inquiry.total_matches === undefined ? count : inquiry.total_matches;
  var html = '<div class="result-card"><section class="answer-block"><div class="answer-block-head"><h3>Inquiry result</h3>' +
    chip(count ? 'answered' : 'no_matches') + '</div>';
  html += '<p class="answer-lead">' + (count
    ? escapeHtml('Found ' + total + ' recorded question' + (total === 1 ? '' : 's') +
      ' the employee asked about the payment-gateway Confluence space in the last 30 days' +
      (inquiry.has_more ? '; the oldest ' + count + ' are shown here, and the Audit trail page pages through the rest. '
        : '. ') +
      'Each one shows what was asked, which sources were checked and what came back. ' +
      'For any other user, space or document, use the search on the Audit trail page.')
    : 'No recorded activity matches yet. Run Case 2 as Employee, then switch to Auditor and run this again.') + '</p></section>';
  inquiry.entries.forEach(function (entry) {
    html += '<section class="result-section inquiry-entry"><p><strong>When</strong> ' + escapeHtml(entry.timestamp) + '</p>';
    html += '<p><strong>Question asked</strong> ' + escapeHtml(entry.question) + '</p>';
    html += '<p><strong>Sources retrieved</strong> ' + escapeHtml(entry.retrieved_ids.join(', ') || 'none') + '</p>';
    html += '<p><strong>Access decisions</strong></p><ul>';
    entry.decisions.forEach(function (decision) {
      html += '<li>' + escapeHtml(platformName(decision.platform) + ' · ' + decision.source_id) +
        ' ' + chip(decision.allowed ? 'allowed' : 'denied') + '</li>';
    });
    html += '</ul><p><strong>Answer given</strong></p><pre class="answer-pre">' +
      escapeHtml(entry.answer == null ? 'No answer was released.' : entry.answer) + '</pre></section>';
  });
  var tech = '<p><strong>Mode</strong> <code>simulated</code></p>';
  tech += '<p><strong>Audit chain valid</strong> ' + boolChip(inquiry.integrity.chain_valid, true) + '</p>';
  var witness = inquiry.integrity.witness || {};
  tech += '<p class="muted small">Both query routes are covered, including queries stopped before an answer. ' +
    (witness.configured
      ? (inquiry.integrity.completeness_unproven
        ? escapeHtml(String(witness.unwitnessed_tail_events)) + ' newest event(s) are not yet in the audit witness.'
        : 'Every event matches the separate audit witness. Removing the newest events from the database and the witness together would not show here; a checkpoint exported after them and kept elsewhere catches that.')
      : 'No audit witness is configured, so removal of the newest events would not be detected.') + '</p>';
  if (inquiry.retention) {
    tech += '<p><strong>Retention</strong> ';
    if (inquiry.retention.policy) {
      tech += escapeHtml(String(inquiry.retention.policy.max_age_days)) + ' days, at most ' +
        escapeHtml(String(inquiry.retention.policy.max_entries)) + ' entries';
    } else {
      tech += 'no policy declared';
    }
    tech += ' · ' + escapeHtml(String(inquiry.retention.removed_count)) + ' payloads removed</p>';
    tech += '<p class="muted small">' + escapeHtml(inquiry.retention.note) + '</p>';
  }
  if (inquiry.checkpoint_anchoring) {
    tech += '<p><strong>Checkpoint</strong> verified through checkpoint <code>' +
      escapeHtml(String(inquiry.checkpoint_anchoring.verified_through_checkpoint)) +
      '</code> · ' + escapeHtml(String(inquiry.checkpoint_anchoring.unanchored_tail_events)) +
      ' events after it</p>';
    tech += '<p class="muted small">' + escapeHtml(inquiry.checkpoint_anchoring.note) + '</p>';
  }
  if (inquiry.limit !== undefined) {
    tech += '<p><strong>Paging</strong> page size ' + escapeHtml(String(inquiry.limit)) +
      ' · ' + escapeHtml(String(inquiry.returned)) + ' returned of ' + escapeHtml(String(inquiry.total_matches)) +
      ' · more <code>' + escapeHtml(String(inquiry.has_more)) + '</code>' +
      ' · next-page token ' + (inquiry.next_cursor ? '<code>issued</code>' : '<code>none</code>') + '</p>';
  }
  html += '<details class="tech-details"><summary>Technical details for reviewers: chain integrity, retention and paging</summary>' +
    '<div class="tech-body">' + tech + '</div></details></div>';
  container.innerHTML = html;
}

function chipTone(text) {
  if (/^(answered|fresh|allowed|supported|completed|within_budget|valid)$/.test(text)) return 'ok';
  if (/^(denied|unsupported|failed|error|invalid|refused)$/.test(text)) return 'bad';
  if (/stale|pending|partial|abstain|over_budget|late|degraded|review|not_run/.test(text)) return 'warn';
  return '';
}

function chip(value, tone) {
  var text = value == null ? '' : String(value);
  tone = tone || chipTone(text);
  return '<code class="chip' + (tone ? ' chip--' + tone : '') + '">' + escapeHtml(text) + '</code>';
}

function boolChip(value, expected) {
  return chip(value, String(value) === String(expected) ? 'ok' : 'bad');
}

function escapeHtml(text) {
  if (text == null) return '';
  var div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}
