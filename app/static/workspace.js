'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const base = new URL('./', location.href);
let operatorKey = '', currentReview = null, currentTrace = null, catalog = [], reviews = [];
const label = value => String(value).replaceAll('_', ' ');
const auth = () => operatorKey ? {Authorization: 'Bearer ' + operatorKey} : {};
async function api(path, options = {}) {
  const response = await fetch(new URL(path, base), { ...options, headers: {...auth(), ...(options.body && typeof options.body === 'string' ? {'Content-Type':'application/json'} : {}), ...options.headers} });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(x => x.msg).join('; ') : 'Request failed (' + response.status + ').');
  }
  return response;
}
async function json(path, options) { return (await api(path, options)).json(); }
function status(target, text, error = false) { const node = $(target); node.textContent = text; node.classList.toggle('error', error); }
function detail(title, value) { $('#dialog-title').textContent = title; $('#dialog-content').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); $('#detail-dialog').showModal(); }
function tab(name) {
  document.querySelectorAll('.tab-panel').forEach(x => x.hidden = x.id !== name);
  document.querySelectorAll('.nav-button').forEach(x => x.classList.toggle('active', x.dataset.tab === name));
  $('#breadcrumb').textContent = ({research:'Research', review:'Design reviews', library:'Source library'})[name];
  if (name === 'review') refreshHistory();
  window.scrollTo({top:0, behavior:'smooth'});
}
document.querySelectorAll('[data-tab]').forEach(x => x.addEventListener('click', () => tab(x.dataset.tab)));
document.querySelectorAll('[data-question]').forEach(x => x.addEventListener('click', () => {$('#question').value = x.dataset.question; $('#question').focus();}));
$('#close-dialog').onclick = () => $('#detail-dialog').close();
$('#access-button').onclick = () => $('#access-dialog').showModal();
$('#close-access').onclick = () => $('#access-dialog').close();
$('#access-form').onsubmit = event => { event.preventDefault(); operatorKey = $('#operator-key').value; $('#operator-key').value = ''; $('#access-dialog').close(); refreshHistory(); };
$('#clear-key').onclick = () => { operatorKey = ''; $('#operator-key').value = ''; $('#access-dialog').close(); refreshHistory(); };

function citation(source) {
  return '<article class="card citation"><div class="citation-heading"><span class="citation-number">' + esc(source.citation_id) + '</span><div><h3>' + esc(source.document_title) + '</h3><small>' + esc(source.publisher) + ' · ' + esc(source.version) + ' · physical PDF page ' + esc(source.page_start ?? '—') + '</small></div></div><p>' + esc(source.text.slice(0, 340)) + (source.text.length > 340 ? '…' : '') + '</p><details><summary>Read the full indexed passage</summary><p>' + esc(source.text) + '</p></details><a target="_blank" rel="noreferrer" href="' + esc(new URL('v1/evidence/' + source.chunk_id, base).href) + '">View cited passage & source record ↗</a></article>';
}
$('#question-form').onsubmit = async event => {
  event.preventDefault(); $('#ask-button').disabled = true; status('#search-status', 'Searching the selected source snapshots…');
  try {
    const body = {question:$('#question').value.trim(), as_of:$('#as-of').value || null, generate_answer:$('#generate').checked, document_ids:$('#scope').value ? [Number($('#scope').value)] : null};
    const result = await json('v1/query', {method:'POST',body:JSON.stringify(body)});
    currentTrace = result.trace_id; $('#search-results').hidden = false;
    $('#answer-card').innerHTML = '<span class="tag">' + esc(label(result.status)) + '</span><div>' + esc(result.answer) + '</div>';
    $('#citations').innerHTML = result.citations.map(citation).join('');
    status('#search-status', result.citations.length + ' passages · ' + result.latency_ms + ' ms · ' + result.retrieval_version);
  } catch (error) { status('#search-status', error.message, true); }
  finally { $('#ask-button').disabled = false; }
};
$('#trace-button').onclick = async () => { try { detail('Request trace', await json('v1/traces/' + currentTrace)); } catch (error) { detail('Trace access', error.message); } };

async function refreshHistory() {
  try {
    reviews = await json('v1/reviews');
    $('#review-history').innerHTML = reviews.length ? reviews.map(r => '<button class="history-item" data-review="' + esc(r.id) + '">' + esc(r.title) + '<small>' + esc(r.created_at) + ' · revision ' + r.revision + '</small></button>').join('') : 'No reviews yet. Load the example to start.';
    document.querySelectorAll('[data-review]').forEach(button => button.onclick = async () => {
      try { renderReview(await json('v1/reviews/' + button.dataset.review)); $('#review-results').scrollIntoView({behavior:'smooth'}); }
      catch(error) { status('#review-status',error.message,true); }
    });
    updateCompareOptions();
  } catch (error) { $('#review-history').textContent = error.message; }
}
function updateCompareOptions() {
  $('#compare-review').innerHTML = '<option value="">Choose a review</option>' + reviews.filter(r => r.id !== currentReview?.id).map(r => '<option value="' + esc(r.id) + '">' + esc(r.title) + ' · ' + esc(r.created_at) + '</option>').join('');
}
$('#refresh-history').onclick = refreshHistory;
$('#load-example').onclick = async () => {
  try { const sample = await json('v1/examples/design'); $('#review-title').value = sample.title; $('#review-content').value = sample.content; status('#review-status','Illustrative example loaded. It intentionally contains gaps and planned controls.'); }
  catch(error) { status('#review-status',error.message,true); }
};
$('#document-file').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 3000000) { status('#review-status','Choose a file smaller than 3 MB.',true); return; }
  status('#review-status','Extracting document text…');
  try {
    const extracted = await json('v1/documents/extract', {method:'POST',body:await file.arrayBuffer(),headers:{'Content-Type':'application/octet-stream'}});
    $('#review-content').value = extracted.content; if (!$('#review-title').value) $('#review-title').value = file.name;
    status('#review-status',extracted.content.length.toLocaleString() + ' characters extracted. Check the text before reviewing.');
  } catch(error) { status('#review-status',error.message,true); }
};
$('#review-form').onsubmit = async event => {
  event.preventDefault(); const selected = [...document.querySelectorAll('#topic-list input:checked')].map(x => x.value);
  if (!selected.length) { status('#review-status','Select at least one review topic.',true); return; }
  $('#review-button').disabled = true; status('#review-status','Finding guidance and candidate evidence…');
  try {
    const report = await json('v1/reviews',{method:'POST',body:JSON.stringify({title:$('#review-title').value,content:$('#review-content').value,control_ids:selected,as_of:$('#review-as-of').value || null})});
    renderReview(report); await refreshHistory(); status('#review-status','Review saved. Inspect the evidence and record your assessment below.');
    $('#review-results').scrollIntoView({behavior:'smooth'});
  } catch(error) { status('#review-status',error.message,true); }
  finally { $('#review-button').disabled = false; }
};

function renderReview(report) {
  currentReview = report; $('#review-results').hidden = false; $('#report-title').textContent = report.title;
  $('#report-meta').textContent = 'Revision ' + report.revision + ' · ' + report.id.slice(0,8) + ' · corpus ' + report.corpus_snapshot.slice(0,12) + ' · ' + report.latency_ms + ' ms';
  const found = report.findings.filter(f => f.discovery_status === 'needs_review').length;
  const unknown = report.findings.length - found;
  const decided = report.findings.filter(f => f.human_decision).length;
  $('#review-summary').innerHTML = '<div class="summary-card"><strong>' + found + '</strong><span>Topics with candidate evidence</span></div><div class="summary-card warn"><strong>' + unknown + '</strong><span>Topics needing more evidence</span></div><div class="summary-card"><strong>' + decided + ' / ' + report.findings.length + '</strong><span>Human decisions recorded</span></div>';
  $('#review-diff').textContent = '';
  $('#findings').innerHTML = report.findings.map(f => {
    const internal = f.internal_evidence.map(e => '<div class="evidence-excerpt"><small>Submitted passage ' + e.passage + ' · matched: ' + esc(e.matched_terms.join(', ')) + '</small><p>' + esc(e.text) + '</p>' + (e.caution ? '<div class="caution">' + esc(e.caution) + '</div>' : '') + '</div>').join('') || '<p class="muted">No matching passage found. Request more documentation before drawing a conclusion.</p>';
    const guidance = f.guidance.map(g => '<div class="evidence-excerpt"><small>' + esc(g.document_title) + ' · v' + esc(g.version) + ' · p.' + esc(g.page_start) + '</small><p>' + esc(g.text) + '</p><a target="_blank" rel="noreferrer" href="' + esc(new URL('v1/evidence/' + g.chunk_id, base).href) + '">Inspect primary source ↗</a></div>').join('') || '<p class="muted">No supporting guidance retrieved in the selected scope/date. Do not assess this topic from this report alone.</p>';
    const decisions = ['documented','partially_documented','insufficient_evidence','not_applicable'];
    return '<article class="card finding"><div class="finding-head"><h3>' + esc(f.title) + '</h3><span class="status-badge">' + esc(label(f.discovery_status)) + '</span></div><div class="finding-grid"><div><h4>YOUR DOCUMENTATION</h4>' + internal + '</div><div><h4>PRIMARY-SOURCE GUIDANCE</h4>' + guidance + '</div></div><div class="requested"><strong>Suggested evidence request</strong><br>' + esc(f.suggested_evidence) + '</div><form class="decision-form" data-control="' + esc(f.control_id) + '"><label>Your assessment<select name="assessment" required><option value="">Choose a decision</option>' + decisions.map(d => '<option value="' + d + '"' + (f.human_decision?.status === d ? ' selected' : '') + '>' + esc(label(d)) + '</option>').join('') + '</select></label><label>Rationale<input name="rationale" required minlength="10" maxlength="2000" value="' + esc(f.human_decision?.rationale || '') + '" placeholder="Why does the evidence support your decision?"></label><button class="secondary" type="submit">Record decision</button></form><div class="decision-status" role="status">' + (f.human_decision ? 'Recorded: ' + esc(label(f.human_decision.status)) : 'Awaiting your assessment') + '</div></article>';
  }).join('');
  document.querySelectorAll('.decision-form').forEach(form => form.onsubmit = async event => {
    event.preventDefault(); const message = form.parentElement.querySelector('.decision-status'); const button = form.querySelector('button'); button.disabled = true;
    try {
      const updated = await json('v1/reviews/' + currentReview.id + '/findings/' + form.dataset.control,{method:'PATCH',body:JSON.stringify({status:form.elements.assessment.value,rationale:form.elements.rationale.value,expected_revision:currentReview.revision})});
      currentReview = updated; $('#report-meta').textContent = 'Revision ' + updated.revision + ' · ' + updated.id.slice(0,8) + ' · corpus ' + updated.corpus_snapshot.slice(0,12);
      message.textContent = 'Decision recorded in the audit trail.'; message.classList.remove('error');
      const count = updated.findings.filter(f => f.human_decision).length; $('#review-summary').lastElementChild.querySelector('strong').textContent = count + ' / ' + updated.findings.length;
      await refreshHistory();
    } catch(error) { message.textContent = error.message; message.classList.add('error'); }
    finally { button.disabled = false; }
  });
  updateCompareOptions();
}
async function download(format) {
  if (!currentReview) return;
  try { const response = await api('v1/reviews/' + currentReview.id + '/export?format=' + format); const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a'); a.href = url; a.download = 'EvidenceTrace-' + currentReview.id.slice(0,8) + (format === 'json' ? '.json' : '.md'); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  catch(error) { detail('Export unavailable',error.message); }
}
$('#export-markdown').onclick = () => download('markdown'); $('#export-json').onclick = () => download('json');
$('#compare-button').onclick = async () => {
  if (!$('#compare-review').value || !currentReview) return;
  try { const diff = await json('v1/reviews/compare',{method:'POST',body:JSON.stringify({before_id:$('#compare-review').value,after_id:currentReview.id})});
    $('#review-diff').innerHTML = '<p class="muted">Corpus ' + (diff.corpus_changed ? 'changed between reviews; interpretation may differ.' : 'unchanged between reviews.') + '</p>' + diff.changes.map(c => '<div class="diff-row">' + esc(c.control_id) + ': ' + esc(label(c.before ?? 'not reviewed')) + ' → ' + esc(label(c.after ?? 'not reviewed')) + ' · evidence ' + (c.evidence_changed ? 'changed' : 'unchanged') + ' · guidance ' + (c.guidance_changed ? 'changed' : 'unchanged') + '</div>').join('');
  } catch(error) { $('#review-diff').textContent = error.message; }
};
$('#source-compare-button').onclick = async () => {
  const target = $('#source-diff-output'); target.hidden = false;
  try { target.textContent = JSON.stringify(await json('v1/sources/compare?before=' + $('#source-before').value + '&after=' + $('#source-after').value),null,2); }
  catch(error) { target.textContent = error.message; }
};

async function initialize() {
  try {
    const [health, library, topics] = await Promise.all([json('health'),json('v1/sources'),json('v1/review-topics')]);
    catalog = library.documents; const active = catalog.filter(d => d.active);
    $('#runtime').textContent = health.local_mode ? 'Local workspace' : 'Hosted workspace';
    $('#capability').textContent = health.generation_enabled ? 'Generation configured' : 'Evidence retrieval enabled';
    $('#generate').disabled = !health.generation_enabled;
    if (!health.review_enabled) {
      $('#review-button').disabled = true;
      $('#document-file').disabled = true;
      status('#review-status', 'Private reviews are unavailable on this deployment. Use the local workspace or a configured persistent operator deployment.');
    }
    $('#generation-note').textContent = health.generation_enabled ? '(operator access)' : '(provider not configured)';
    $('#hero-pages').textContent = library.total_pages.toLocaleString(); $('#hero-publishers').textContent = [...new Set(active.map(d => d.publisher))].join(' + ');
    $('#stat-documents').textContent = active.length; $('#stat-chunks').textContent = library.total_chunks.toLocaleString(); $('#stat-snapshot').textContent = library.snapshot.slice(0,10);
    $('#scope').insertAdjacentHTML('beforeend', active.map(d => '<option value="' + d.id + '">' + esc(d.framework) + ' · ' + esc(d.version) + '</option>').join(''));
    $('#topic-list').innerHTML = topics.map(t => '<label class="topic"><input type="checkbox" checked value="' + esc(t.id) + '">' + esc(t.title) + '</label>').join('');
    $('#library-list').innerHTML = active.map(d => '<article class="card source-card"><span class="tag">' + esc(d.publisher) + ' · ' + esc(d.framework) + '</span><h2>' + esc(d.title) + '</h2><div class="source-meta"><span>Edition ' + esc(d.version) + '</span><span>' + d.page_count + ' pages</span><span>' + d.chunk_count + ' passages</span></div><p class="muted">Published: ' + esc(d.effective_from || 'Not verified — excluded from dated searches') + '<br>Retrieved: ' + esc(d.retrieved_at?.slice(0,10) || 'Not recorded') + '</p><div class="source-hash mono">SHA-256<br>' + esc(d.source_sha256 || 'No raw-source fingerprint') + '</div><a href="' + esc(/^https?:/.test(d.source_uri) ? d.source_uri : '#') + '" target="_blank" rel="noreferrer">Open publisher record ↗</a></article>').join('');
    const options = catalog.map(d => '<option value="' + d.id + '">' + esc(d.framework) + ' · ' + esc(d.version) + ' · snapshot ' + d.id + (d.active ? ' (current)' : '') + '</option>').join('');
    $('#source-before').innerHTML = options; $('#source-after').innerHTML = options;
  } catch(error) { status('#search-status',error.message,true); $('#capability').textContent = 'Service unavailable'; }
}
initialize();
