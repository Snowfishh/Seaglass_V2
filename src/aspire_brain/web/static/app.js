'use strict';
let csrf = '';
const result = document.getElementById('result');
const notice = document.getElementById('notice');
const persona = document.getElementById('persona');
let generation = 0;
const byId = (id) => document.getElementById(id);
const label = (value) => String(value ?? '').replaceAll('_', ' ');
// Display names only; the server still identifies each persona by its id.
const PERSONA_GROUPS = [
  {label: 'Travel policy · Singapore', ids: ['employee', 'finance_lead', 'policy_admin', 'auditor', 'other_tenant', 'disabled']},
  {label: 'Fintech operations · Confluence, Jira, Slack, Drive', ids: ['user-a', 'user-b', 'fintech_auditor', 'fintech_admin']},
];
const PERSONA_NAMES = {
  employee: 'Employee', finance_lead: 'Finance lead', policy_admin: 'Policy admin', auditor: 'Auditor',
  other_tenant: 'Other company (tenant B)', disabled: 'Disabled account',
  'user-a': 'User A · can see restricted items', 'user-b': 'User B · general items only',
  fintech_auditor: 'Fintech auditor · audit trail only',
  fintech_admin: 'Fintech platform admin · changes and syncs the platforms',
};
const SHORT_NAMES = {'user-a': 'User A', 'user-b': 'User B', fintech_auditor: 'Fintech auditor',
  fintech_admin: 'Fintech platform admin'};
const PLATFORM_NAMES = {confluence: 'Confluence', jira: 'Jira', slack: 'Slack', drive: 'Google Drive'};
const personaName = (id) => SHORT_NAMES[id] || PERSONA_NAMES[id] || label(id);
const FINTECH_NOTE = 'User A and User B are also real test accounts on Confluence, Jira, Slack and Google Drive, ' +
  'where a read-only check passed 16 of 16 on 14 October.';
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function api(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin',
    headers: body ? {'Content-Type': 'application/json', 'X-CSRF-Token': csrf} : {},
    body: body ? JSON.stringify(body) : undefined, cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Request unavailable');
  return data;
}
// Example searches for the Reconstruct activity card. Records exist only after someone has asked
// a question, so each example names the question to ask first.
const INQUIRY_EXAMPLES = {
  auditor: [
    {label: "Employee's questions", fields: {subject: 'employee'},
      needs: 'Returns records once Employee has asked a question on the Travel-policy demo page or run Case 1, 2, 3 or 4.'},
    {label: 'Employee in the payment-gateway space',
      fields: {subject: 'employee', platform: 'confluence', parent: 'payment-gateway'},
      needs: 'Returns records once Employee has run Case 2 on the Case demo page.'},
    {label: "Finance lead's questions", fields: {subject: 'finance_lead'},
      needs: 'Returns records once Finance lead has asked a question on the Travel-policy demo page.'},
    {label: "Policy admin's questions", fields: {subject: 'policy_admin'},
      needs: 'Returns records once Policy admin has asked a question on the Travel-policy demo page.'},
    {label: 'Who was denied the finance guide',
      fields: {platform: 'policy_store', parent: 'finance-guide', mode: 'denied'},
      needs: 'Returns records once Employee or Policy admin has asked a question on the Travel-policy demo page.'},
  ],
  fintech_auditor: [
    {label: "User A's questions", fields: {subject: 'user-a'},
      needs: 'Returns records once User A has asked a question on the Case demo page.'},
    {label: "User B's questions", fields: {subject: 'user-b'},
      needs: 'Returns records once User B has asked a question on the Case demo page.'},
    {label: 'Who retrieved the restricted case note',
      fields: {platform: 'confluence', source: 'conf-restricted-case', mode: 'retrieved'},
      needs: "Returns records once User A has asked \"Why is Cedar Quay's payment held?\" on the Case demo page."},
    {label: 'Who was denied the restricted case note',
      fields: {platform: 'confluence', source: 'conf-restricted-case', mode: 'denied'},
      needs: "Returns records once User B has asked \"Why is Cedar Quay's payment held?\" on the Case demo page."},
  ],
};
function showInquiryExamples(principalId) {
  const buttons = byId('inquiry-example-buttons');
  if (!buttons) return;
  const examples = INQUIRY_EXAMPLES[principalId] || [];
  byId('inquiry-examples-intro').classList.toggle('locked', !examples.length);
  byId('inquiry-examples-intro').textContent = examples.length
    ? 'Try an example. It fills the fields below; then choose Search records.'
    : 'Only Auditor and Fintech auditor can search these records. Sign in as one of them to see example searches.';
  byId('inquiry-example-hint').hidden = true;
  buttons.replaceChildren(...examples.map((example) => {
    const button = element('button', example.label, 'button--ghost typed-example');
    button.type = 'button';
    button.addEventListener('click', () => {
      const fields = {subject: '', platform: '', parent: '', source: '', mode: 'retrieved', ...example.fields};
      for (const [key, value] of Object.entries(fields)) byId(`inquiry-${key}`).value = value;
      byId('inquiry-days').value = '30';
      byId('inquiry-example-hint').textContent = example.needs;
      byId('inquiry-example-hint').hidden = false;
    });
    return button;
  }));
}
function identity(data) {
  csrf = data.csrf_token;
  persona.value = data.principal?.id || '';
  byId('identity').textContent = data.principal ? `Signed in as ${personaName(data.principal.id)} · ${data.principal.tenant_id}` : 'Choose a persona to begin.';
  const fintech = ['user-a', 'user-b'].includes(data.principal?.id);
  byId('persona-note').textContent = fintech ? FINTECH_NOTE : '';
  byId('persona-note').hidden = !fintech;
  showInquiryExamples(data.principal?.id);
}
function card(title) {
  const box = element('article', undefined, 'result-card');
  box.append(element('h2', title));
  result.append(box);
  return box;
}
function jsonDetail(parent, title, value) {
  if (!value || (Array.isArray(value) && value.length === 0)) return;
  const details = element('details');
  details.append(element('summary', title), element('pre', JSON.stringify(value, null, 2)));
  parent.append(details);
}
function link(text, url) {
  const node = element('a', text); node.href = url; return node;
}
function renderAnswer(data) {
  const box = card('Answer');
  const head = element('div', undefined, 'answer-head');
  head.append(element('span', label(data.query_status), `status ${data.query_status === 'answered' ? '' : 'review'}`),
    element('h3', label(data.case_outcome)));
  box.append(head, element('p', data.answer, 'answer-text'), element('p', data.scope_notice, 'muted'));
  if (data.review_route) box.append(element('p', `Review route: ${data.review_route}`, 'review-route'));
  if (data.citations?.length) box.append(element('p', `Sources · ${data.citations.length}`, 'citations-title'));
  for (const citation of data.citations || []) {
    const row = element('div', undefined, 'citation');
    const version = citation.document_version_id;
    row.append(link(`${version} · ${citation.source_locator}`,
      `/sources?version=${encodeURIComponent(version)}&chunk=${encodeURIComponent(citation.chunk_id)}`),
      element('p', citation.excerpt || citation.safe_excerpt || ''));
    box.append(row);
  }
  jsonDetail(box, 'Applied rules', data.applied_rules);
  jsonDetail(box, 'Conflicts that need review', data.conflicts);
  jsonDetail(box, 'Evidence that is missing', data.missing_evidence_categories);
  const meta = element('div', undefined, 'answer-meta');
  const ids = element('div');
  ids.append(element('p', `Mode: ${data.provider_mode} · Retrieval: ${data.retrieval_mode}`, 'small muted'),
    element('p', `Request: ${data.request_id} · Audit: ${data.audit_event_id}`, 'small muted'));
  const exportLink = link('Export evidence packet', `/api/packets/${encodeURIComponent(data.request_id)}/export`);
  exportLink.className = 'button button--ghost';
  meta.append(ids, exportLink);
  box.append(meta);
}
function renderSource(data) {
  const box = card(data.version_id || data.document_version_id);
  box.append(element('p', data.source_locator), element('div', data.text, 'source-text'));
  if (data.document_id) box.append(link(`View history: ${data.document_id}`, `/policies?document=${encodeURIComponent(data.document_id)}`));
  box.append(element('p', `Content hash: ${data.content_hash}`, 'small muted'));
}
const STATE_CLASS = {approved: '', draft: 'review', withdrawn: 'withdrawn'};
function renderHistory(data) {
  const now = new Date();
  const today = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-');
  const ordered = [...data].sort((a, b) => String(a.valid_from || a.source_updated_at || '')
    .localeCompare(String(b.valid_from || b.source_updated_at || '')));
  for (const version of ordered) {
    if (version.platform) {
      // Fintech fixture records carry a last-updated time, not an effective-date window.
      const box = card(version.id);
      const head = element('div', undefined, 'version-head');
      head.append(element('span', label(version.state), 'status muted-state'));
      box.append(head, element('p', `${PLATFORM_NAMES[version.platform] || version.platform} ${label(version.source_kind)} · last updated ${version.source_updated_at}`),
        element('p', `Synced into the demo index at ${version.synced_at}`, 'small muted'));
      jsonDetail(box, 'Version details', version);
      continue;
    }
    const state = version.state || version.publication_state || 'approved';
    const current = state === 'approved' && (version.valid_from || '') <= today && (!version.valid_to || today < version.valid_to);
    const box = card(version.id || version.version_id || version.document_version_id || 'Version');
    if (current) box.classList.add('version-current');
    const head = element('div', undefined, 'version-head');
    head.append(element('span', label(state), `status ${STATE_CLASS[state] ?? 'muted-state'}`));
    if (current) head.append(element('span', 'In effect today', 'chip chip--ok'));
    else if (state === 'approved' && version.valid_from > today) head.append(element('span', 'Scheduled', 'chip chip--warn'));
    const from = version.valid_from || 'an unset date';
    box.append(head, element('p', version.valid_to
      ? `In effect from ${from} until ${version.valid_to} (the end date itself is not included)`
      : `In effect from ${from}, with no end date`));
    for (const rule of version.rules || []) {
      const row = element('p', undefined, 'version-rule');
      row.append(element('span', `${label(rule.key)}: `), element('strong', `${rule.currency || ''} ${rule.value} per ${rule.unit}`.trim()));
      if (rule.overrides?.length) row.append(element('span', ` · overrides ${rule.overrides.join(', ')}`, 'muted'));
      box.append(row);
    }
    if (version.supersedes) box.append(element('p', `Supersedes ${version.supersedes}`, 'small muted'));
    jsonDetail(box, 'Version details and links', version);
  }
  if (!data.length) card('No history available for this ID');
}
function renderAudit(data) {
  const box = card(data.integrity.chain_valid ? 'Audit chain is intact' : 'Audit integrity check failed');
  box.append(element('p', completenessNote(data.integrity), 'muted'));
  jsonDetail(box, 'Integrity verification', data.integrity);
  const wrap = element('div', undefined, 'table-wrap');
  const table = element('table');
  const head = element('tr');
  ['Sequence', 'Time', 'Event', 'Principal', 'Request'].forEach((name) => head.append(element('th', name)));
  table.append(head);
  for (const event of data.events) {
    const row = element('tr');
    [event.sequence, event.timestamp, event.event_type, event.principal_id, event.request_id]
      .forEach((value) => row.append(element('td', value)));
    table.append(row);
  }
  wrap.append(table); box.append(wrap);
  if (data.next_offset !== null) {
    const next = element('button', 'Next page');
    next.addEventListener('click', () => loadAudit(data.next_offset));
    box.append(next);
  }
}
function completenessNote(integrity) {
  const witness = integrity.witness || {};
  if (!witness.configured) return 'No audit witness is configured, so removal of the newest events would not be detected.';
  if (witness.truncation_detected) return 'Events recorded by the audit witness are missing from the database.';
  if (!integrity.completeness_unproven) return 'Every event up to the newest one matches the separate audit witness. Removing the newest events from the database and the witness together would not show here; a checkpoint exported after them and kept elsewhere catches that.';
  return `${witness.unwitnessed_tail_events} newest event(s) are not yet in the audit witness.`;
}
function renderInquiry(data) {
  const box = card(data.entries.length ? `${data.total_matches} matching record(s)` : 'No matching records');
  box.append(element('p', completenessNote(data.integrity), 'muted'));
  for (const entry of data.entries) {
    const item = element('section', undefined, 'inquiry-entry');
    item.append(element('h3', `${entry.subject_id} · ${entry.timestamp}`));
    item.append(element('p', `Question: ${entry.question}`));
    item.append(element('p', `Outcome: ${label(entry.query_status)}${entry.error_code ? ` (${label(entry.error_code)})` : ''} · ${entry.operation === 'protected_query' ? 'travel-policy route' : 'four-platform route'}`));
    item.append(element('p', `Retrieved: ${entry.retrieved_ids.join(', ') || 'nothing'}`));
    const list = element('ul');
    for (const decision of entry.decisions) {
      list.append(element('li', `${PLATFORM_NAMES[decision.platform] || label(decision.platform)} · ${decision.source_id}: ${decision.allowed ? 'allowed' : 'denied'}${decision.retrieved ? ', retrieved' : ''}`));
    }
    const decisions = element('details'); decisions.append(element('summary', `Access decisions (${entry.decisions.length})`), list);
    item.append(decisions);
    item.append(element('p', 'Answer given:'), element('pre', entry.answer ?? 'No answer was released.'));
    box.append(item);
  }
  if (data.next_cursor) {
    box.append(element('p', `Showing ${data.returned} of ${data.total_matches}, oldest first.`, 'muted'));
    const next = element('button', 'Next page');
    next.addEventListener('click', () => runInquiry(data.next_cursor));
    box.append(next);
  }
}
// The cursor is bound to the exact filters and window it was issued for, so a continuation
// repeats the previous search's parameters rather than re-reading the form.
let inquiryParams = null;
function runInquiry(cursor) {
  const params = new URLSearchParams(inquiryParams);
  if (cursor) params.set('cursor', cursor);
  perform(() => api(`/api/audit/inquiry?${params}`), renderInquiry, byId('inquiry-notice'));
}
byId('inquiry-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  const days = Math.min(365, Math.max(1, Number(byId('inquiry-days').value) || 30));
  const until = new Date(Date.now() + 60000);
  const params = new URLSearchParams({since: new Date(until - days * 86400000 - 60000).toISOString(),
    until: until.toISOString(), decision_mode: byId('inquiry-mode').value, limit: '50'});
  for (const [key, id] of [['subject_id', 'inquiry-subject'], ['platform', 'inquiry-platform'],
    ['parent_id', 'inquiry-parent'], ['source_id', 'inquiry-source']]) {
    if (byId(id).value.trim()) params.set(key, byId(id).value.trim());
  }
  inquiryParams = params.toString();
  runInquiry(null);
});
function clearNotices() {
  notice.textContent = '';
  const inquiryNotice = byId('inquiry-notice');
  if (inquiryNotice) {inquiryNotice.textContent = ''; inquiryNotice.hidden = true;}
}
// A form can pass its own notice so its errors show under its button instead of the page banner.
async function perform(action, render, target = notice) {
  const current = ++generation;
  result.replaceChildren(); clearNotices();
  const buttons = document.querySelectorAll('main button');
  buttons.forEach((button) => {button.disabled = true;});
  result.setAttribute('aria-busy', 'true');
  try {const data = await action(); if (current === generation) render(data);}
  catch (error) {if (current === generation) {target.textContent = error.message; target.hidden = false;}}
  finally {
    if (current === generation) result.removeAttribute('aria-busy');
    buttons.forEach((button) => {button.disabled = false;});
  }
}
persona.addEventListener('change', async () => {
  generation += 1; result.replaceChildren(); result.removeAttribute('aria-busy'); clearNotices();
  const chosen = persona.value;
  if (!chosen) return;
  persona.disabled = true;
  document.querySelectorAll('main button').forEach((button) => {button.disabled = true;});
  try {const data = await api('/api/demo/session', {user_id: chosen}); identity(data); loadSuggestions(data.principal).catch(() => {});}
  catch (error) {notice.textContent = error.message; identity(await api('/api/session'));}
  finally {persona.disabled = false; document.querySelectorAll('main button').forEach((button) => {button.disabled = false;});}
});
byId('ask-form')?.addEventListener('submit', (event) => {
  event.preventDefault();
  const context = {workflow_id: byId('workflow').value};
  const fields = {'case_date':'case-date','jurisdiction':'jurisdiction','worker_type':'worker-type',
    'project':'project','cost_centre':'cost-centre','expense_amount':'amount','currency':'currency'};
  for (const [key, id] of Object.entries(fields)) if (byId(id).value) context[key] = byId(id).value;
  perform(() => api('/api/queries', {question: byId('question').value, context}), renderAnswer);
});
byId('source-form')?.addEventListener('submit', (event) => {
  event.preventDefault(); perform(() => api(`/api/sources/${encodeURIComponent(byId('version-id').value)}/${encodeURIComponent(byId('chunk-id').value)}`), renderSource);
});
byId('history-form')?.addEventListener('submit', (event) => {
  event.preventDefault(); perform(() => api(`/api/policies/${encodeURIComponent(byId('document-id').value)}/versions`), renderHistory);
});
function loadAudit(offset = 0) {
  const params = new URLSearchParams({offset: String(offset)});
  if (byId('trace-id').value.trim()) params.set('request_id', byId('trace-id').value.trim());
  return perform(() => api(`/api/audit/events?${params}`), renderAudit);
}
byId('load-audit')?.addEventListener('click', () => loadAudit());
// Suggested values come only from records the current persona can already read.
let lookupSources = [];
function fillList(id, entries) {
  const list = byId(id);
  if (!list) return;
  list.replaceChildren(...entries.map(([value, text]) => {
    const node = element('option', text); node.value = value; return node;
  }));
}
function fillChunkList() {
  const version = byId('version-id')?.value.trim();
  fillList('chunk-options', lookupSources.filter((s) => !version || s.version_id === version)
    .map((s) => [s.chunk_id, s.source_locator]));
}
async function loadSuggestions(principal) {
  lookupSources = [];
  ['version-options', 'chunk-options', 'document-options', 'trace-options'].forEach((id) => fillList(id, []));
  if (!principal) return;
  if (byId('source-form') || byId('history-form')) {
    const data = await api('/api/lookup-suggestions');
    lookupSources = data.sources;
    const versions = [...new Map(data.sources.map((s) => [s.version_id, s.source_locator.split(' · ')[0]])).entries()];
    fillList('version-options', versions);
    fillChunkList();
    fillList('document-options', data.documents.map((id) => [id, id]));
  }
  if (byId('trace-id') && principal.roles.includes('audit')) {
    const data = await api('/api/audit/events?limit=100&newest_first=true');
    const seen = new Map();
    for (const event of data.events) {
      // Skip the page's own bookkeeping reads so the list shows real activity.
      if (/^(audit_view|lookup_suggestions|session_changed)/.test(event.event_type)) continue;
      if (event.request_id && !seen.has(event.request_id)) {
        seen.set(event.request_id, `${label(event.event_type)} · ${event.principal_id} · ${event.timestamp}`);
      }
    }
    fillList('trace-options', [...seen.entries()].slice(0, 25));
  }
}
byId('version-id')?.addEventListener('input', fillChunkList);
async function initialize() {
  const data = await api('/api/session');
  const offered = new Set(data.personas);
  const option = (id) => {const node = element('option', PERSONA_NAMES[id] || label(id)); node.value = id; return node;};
  for (const group of PERSONA_GROUPS) {
    const ids = group.ids.filter((id) => offered.has(id));
    if (!ids.length) continue;
    const node = element('optgroup'); node.label = group.label;
    ids.forEach((id) => {node.append(option(id)); offered.delete(id);});
    persona.append(node);
  }
  offered.forEach((id) => persona.append(option(id)));
  persona.disabled = !data.demo_mode; identity(data);
  loadSuggestions(data.principal).catch(() => {});
  if (!data.demo_mode) notice.textContent = 'Demo personas are switched off, and there is no other way to sign in.';
  const params = new URLSearchParams(location.search);
  if (byId('source-form') && params.has('version') && params.has('chunk')) {
    byId('version-id').value = params.get('version'); byId('chunk-id').value = params.get('chunk');
    if (data.principal) byId('source-form').requestSubmit();
  }
  if (byId('history-form') && params.has('document')) {
    byId('document-id').value = params.get('document');
    if (data.principal) byId('history-form').requestSubmit();
  }
}
initialize().catch(() => {notice.textContent = 'Could not start a session. Check the local setup and reload.';});
