'use strict';
let csrf = '';
const result = document.getElementById('result');
const notice = document.getElementById('notice');
const persona = document.getElementById('persona');
let generation = 0;
const byId = (id) => document.getElementById(id);
const label = (value) => String(value ?? '').replaceAll('_', ' ');
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
function identity(data) {
  csrf = data.csrf_token;
  persona.value = data.principal?.id || '';
  byId('identity').textContent = data.principal ? `${label(data.principal.id)} · ${data.principal.tenant_id}` : 'Select a persona to begin';
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
  const box = card('Evidence response');
  box.append(element('span', label(data.query_status), `status ${data.query_status === 'answered' ? '' : 'review'}`),
    element('h3', label(data.case_outcome)), element('p', data.answer),
    element('p', data.scope_notice, 'muted'));
  if (data.review_route) box.append(element('p', `Review route: ${data.review_route}`));
  for (const citation of data.citations || []) {
    const row = element('div', undefined, 'citation');
    const version = citation.document_version_id;
    row.append(link(`${version} · ${citation.source_locator}`,
      `/sources?version=${encodeURIComponent(version)}&chunk=${encodeURIComponent(citation.chunk_id)}`),
      element('p', citation.excerpt || citation.safe_excerpt || ''));
    box.append(row);
  }
  jsonDetail(box, 'Applied rules', data.applied_rules);
  jsonDetail(box, 'Conflicts requiring review', data.conflicts);
  jsonDetail(box, 'Missing evidence categories', data.missing_evidence_categories);
  box.append(element('p', `Mode: ${data.provider_mode} · Audit: ${data.audit_event_id}`, 'small muted'),
    link('Export evidence packet', `/api/packets/${encodeURIComponent(data.request_id)}/export`));
}
function renderSource(data) {
  const box = card(data.version_id || data.document_version_id);
  box.append(element('p', data.source_locator), element('div', data.text, 'source-text'));
  if (data.document_id) box.append(link(`View history: ${data.document_id}`, `/policies?document=${encodeURIComponent(data.document_id)}`));
  box.append(element('p', `Content hash: ${data.content_hash}`, 'small muted'));
}
function renderHistory(data) {
  for (const version of data) {
    const box = card(version.id || version.version_id || version.document_version_id || 'Version');
    box.append(element('p', `Effective: ${version.valid_from || '—'} to ${version.valid_to || 'open end'} (end exclusive)`),
      element('span', label(version.state || version.publication_state || 'approved'), 'status'));
    jsonDetail(box, 'Readable version metadata and relationships', version);
  }
  if (!data.length) card('No readable history available');
}
function renderAudit(data) {
  const box = card(data.integrity.chain_valid ? 'Audit chain valid' : 'Audit integrity check failed');
  box.append(element('p', 'Completeness remains unproven without an independently retained checkpoint.', 'muted'));
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
}
async function perform(action, render) {
  const current = ++generation;
  result.replaceChildren(); notice.textContent = '';
  const buttons = document.querySelectorAll('main button');
  buttons.forEach((button) => {button.disabled = true;});
  try {const data = await action(); if (current === generation) render(data);}
  catch (error) {if (current === generation) notice.textContent = error.message;}
  finally {buttons.forEach((button) => {button.disabled = false;});}
}
persona.addEventListener('change', async () => {
  generation += 1; result.replaceChildren(); notice.textContent = '';
  const chosen = persona.value;
  if (!chosen) return;
  persona.disabled = true;
  try {identity(await api('/api/demo/session', {user_id: chosen}));}
  catch (error) {notice.textContent = error.message; identity(await api('/api/session'));}
  finally {persona.disabled = false;}
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
byId('load-audit')?.addEventListener('click', () => perform(() => api('/api/audit/events'), renderAudit));
async function initialize() {
  const data = await api('/api/session');
  for (const id of data.personas) {const option = element('option', label(id)); option.value = id; persona.append(option);}
  persona.disabled = !data.demo_mode; identity(data);
  if (!data.demo_mode) notice.textContent = 'Demo identity is disabled. Authentication is unavailable.';
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
initialize().catch(() => {notice.textContent = 'Session unavailable. Check local configuration and reload.';});
