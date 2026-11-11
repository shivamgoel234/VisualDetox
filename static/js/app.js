const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const STEP_LABEL = {
  screenshotting: 'Screenshotting',
  dom_checks:     'DOM checks',
  finding_issues: 'Finding issues',
  outlining:      'Outlining problems',
};

let currentReport = null;
let currentVP     = 'desktop';
let retryFn       = null;
let liveTimers    = {};   // stepId → interval id
let liveEnabled = true;

document.addEventListener('DOMContentLoaded', async () => {
  loadConfig();
  wireDemoButtons();
  document.getElementById('audit-form').addEventListener('submit', onRunClick);
  document.getElementById('open-sample-btn').addEventListener('click', () => replayRun('75afaa44'));
  document.getElementById('url-input').addEventListener('input', () => {
    document.querySelectorAll('.site-option').forEach(button => button.setAttribute('aria-pressed', 'false'));
  });
  document.getElementById('show-runs-btn').addEventListener('click', toggleRuns);
  document.getElementById('retry-btn').addEventListener('click', () => retryFn && retryFn());
  document.getElementById('error-home-btn').addEventListener('click', () => showView('home'));
  document.getElementById('home-btn').addEventListener('click', () => showView('home'));
  document.getElementById('feature-btn').addEventListener('click', featureCurrent);
  document.getElementById('run-again-btn').addEventListener('click', () => {
    if (!currentReport?.url) return;
    const url = new URL(currentReport.url);
    const localDemo = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      && /^\/demo-sites\/demo[1-4]\.html$/.test(url.pathname);
    runLive(localDemo ? new URL(url.pathname, location.origin).href : url.href);
  });
  const tabs = [...document.querySelectorAll('.seg')];
  tabs.forEach((s, index) => {
    s.addEventListener('keydown', event => {
      const positions = {
        ArrowLeft: (index + tabs.length - 1) % tabs.length,
        ArrowRight: (index + 1) % tabs.length,
        Home: 0,
        End: tabs.length - 1
      };
      if (!Object.hasOwn(positions, event.key)) return;
      event.preventDefault();
      const next = tabs[positions[event.key]];
      next.click();
      next.focus();
    });
    s.addEventListener('click', () => {
      tabs.forEach(tab => {
        const active = tab === s;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
        tab.tabIndex = active ? 0 : -1;
      });
      if (s.id === 'changes-tab') {
        // Show diff panel, hide slider
        document.getElementById('result-slider-wrap').hidden = true;
        document.getElementById('diff-panel').hidden = false;
        if (currentReport) renderDiff(currentReport);
      } else {
        currentVP = s.dataset.viewport;
        document.getElementById('result-slider-wrap').hidden = false;
        document.getElementById('diff-panel').hidden = true;
        if (currentReport) renderSlider(currentReport);
      }
    });
  });
  createSlider(
    document.getElementById('hero-slider-container'),
    '/sample-runs/75afaa44/before_desktop.png',
    '/sample-runs/75afaa44/after_r1_desktop.png'
  );
});

async function loadConfig() {
  try {
    const config = await apiFetch('/api/config');
    if (config.repo_url) {
      document.getElementById('nav-github').href = config.repo_url;
    }
    liveEnabled = config.mock_mode || config.api_key_set;
    document.getElementById('run-live-btn').disabled = !liveEnabled;
    document.getElementById('audit-status').textContent = config.mock_mode
      ? 'Fixture mode. Use a demo page or browse saved reports.'
      : liveEnabled ? '' : 'Set GEMINI_API_KEY in .env to enable audits.';
  } catch {
    document.getElementById('audit-status').textContent = 'Could not load the audit settings. Reload to try again.';
  }
}

function wireDemoButtons() {
  const input = document.getElementById('url-input');
  const demos = document.querySelectorAll('.site-option');
  demos.forEach(button => {
    button.addEventListener('click', () => {
      input.value = new URL(button.dataset.path, location.origin).href;
      demos.forEach(demo => demo.setAttribute('aria-pressed', String(demo === button)));
      input.focus();
    });
  });
}

function onRunClick(event) {
  event.preventDefault();
  if (liveEnabled) runLive(document.getElementById('url-input').value.trim());
}

function showView(name) {
  document.querySelectorAll('.view').forEach(view => view.hidden = true);
  const view = document.getElementById(name + '-view');
  view.hidden = false;
  view.querySelector('[tabindex="-1"]')?.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

async function runLive(url) {
  if (!liveEnabled) return;
  showView('progress');
  clearSteps();
  stopTimers();
  document.getElementById('replay-notice').hidden = true;
  setRunBtnLoading(true);
  retryFn = () => runLive(url);

  // Seed with the 4 known initial steps
  Object.keys(STEP_LABEL).forEach(id => addStep(id, STEP_LABEL[id]));

  try {
    const resp = await fetch('/api/run/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    if (!resp.ok) {
      const error = await resp.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Could not start the audit.');
    }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let finished = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const evts = buf.split('\n\n');
      buf = evts.pop();
      for (const event of evts) finished = parseSSE(event) || finished;
    }
    if (!finished) throw new Error('The audit ended before a report arrived. Try again.');
  } catch (err) {
    stopTimers();
    showError(err.message || 'Network error — is the server running?');
  } finally {
    setRunBtnLoading(false);
  }
}

function parseSSE(str) {
  const lines = str.split('\n');
  let type = 'message', data = '';
  for (const l of lines) {
    if (l.startsWith('event: ')) type = l.slice(7).trim();
    if (l.startsWith('data: '))  data = l.slice(6);
  }
  if (!data) return;
  let obj; try { obj = JSON.parse(data); } catch { return; }
  if (type === 'step') {
    if (obj.step === 'fixing'    && obj.status === 'started')
      addStep('fixing_r'    + obj.round, 'Fixing — round ' + obj.round);
    if (obj.step === 'verifying' && obj.status === 'started')
      addStep('verifying_r' + obj.round, 'Verifying — round ' + obj.round);
    updateStep(obj.step, obj.status, obj);
    setTimelineFill();
  } else if (type === 'done') {
    stopTimers(); setTimelineFill(true);
    renderResult(obj);
    return true;
  } else if (type === 'error') {
    stopTimers();
    showError(obj.message || 'Something went wrong.');
    return true;
  }
}

function setRunBtnLoading(on) {
  const btn = document.getElementById('run-live-btn');
  if (!btn) return;
  if (on) { btn.classList.add('loading'); btn.querySelector('.btn-label').textContent = 'Running…'; }
  else    { btn.classList.remove('loading'); btn.querySelector('.btn-label').textContent = 'Run audit'; }
}

async function replayRun(runId) {
  showView('progress');
  clearSteps(); stopTimers();
  document.getElementById('replay-notice').hidden = false;
  retryFn = () => replayRun(runId);
  try {
    const report = await apiFetch('/api/run/' + runId);
    renderResult(report);
  } catch (e) { showError(e.message); }
}

function clearSteps() {
  document.getElementById('steps-container').innerHTML = '';
  setTimelineFill();
}

function addStep(id, label) {
  const li = document.createElement('li');
  li.className = 'step-item';
  li.id = 'step-' + id;
  const idx = document.getElementById('steps-container').children.length;
  li.style.animationDelay = REDUCED ? '0ms' : idx * 40 + 'ms';
  li.innerHTML =
    '<div class="step-icon" aria-hidden="true"></div>' +
    '<div class="step-body">' +
      '<div class="step-name">' + esc(label) + '</div>' +
      '<div class="step-detail"></div>' +
    '</div>' +
    '<div class="step-time" aria-live="polite"></div>';
  document.getElementById('steps-container').appendChild(li);
}

function updateStep(step, status, data) {
  let id = step;
  if (step === 'fixing')    id = 'fixing_r'    + (data.round || 1);
  if (step === 'verifying') id = 'verifying_r' + (data.round || 1);
  const li = document.getElementById('step-' + id);
  if (!li) return;
  const icon   = li.querySelector('.step-icon');
  const detail = li.querySelector('.step-detail');
  const time   = li.querySelector('.step-time');

  if (status === 'started') {
    icon.className = 'step-icon spinning';
    // Live elapsed timer
    const t0 = Date.now();
    liveTimers[id] = setInterval(() => {
      time.textContent = ((Date.now() - t0) / 1000).toFixed(1) + 's';
    }, 100);
  } else if (status === 'done') {
    clearInterval(liveTimers[id]); delete liveTimers[id];
    // Draw SVG check
    const tpl = document.getElementById('svg-check-tpl');
    const svg = tpl ? tpl.cloneNode(true) : null;
    icon.className = 'step-icon done';
    icon.innerHTML = '';
    if (svg) { svg.removeAttribute('id'); svg.style.display = ''; icon.appendChild(svg); }
    if (data.elapsed) time.textContent = data.elapsed + 's';
    if (data.count  != null) detail.textContent = data.count  + ' found';
    if (data.fixed  != null) detail.textContent = data.fixed  + ' fixed, ' + data.unfixed + ' open';
  }
}

function stopTimers() { Object.values(liveTimers).forEach(clearInterval); liveTimers = {}; }

function setTimelineFill(complete = false) {
  const fill = document.getElementById('timeline-fill');
  if (!fill) return;
  if (complete) { fill.style.height = '100%'; return; }
  const all  = document.querySelectorAll('.step-item').length;
  const done = document.querySelectorAll('.step-icon.done').length;
  fill.style.height = all ? Math.round((done / all) * 100) + '%' : '0%';
}

function renderResult(report) {
  currentReport = report;
  document.getElementById('feature-status').textContent = '';

  const found  = report.total_issues || 0;
  const fixed  = report.total_fixed  || 0;
  const rounds = report.rounds_used  || 0;
  const raw    = report.raw_findings_count || 0;

  // Reset tab state — always start on slider view
  document.getElementById('result-slider-wrap').hidden = false;
  document.getElementById('diff-panel').hidden = true;

  // Default to Mobile tab when the run has mobile-only or mobile+desktop issues
  const hasMobileIssue = (report.per_issue || []).some(i => i.viewport === 'mobile');
  const defaultVP = hasMobileIssue ? 'mobile' : 'desktop';
  {
    currentVP = defaultVP;
    document.querySelectorAll('.seg').forEach(s => {
      const match = s.dataset.viewport === defaultVP;
      s.classList.toggle('active', match);
      s.setAttribute('aria-selected', String(match));
      s.tabIndex = match ? 0 : -1;
    });
  }

  document.getElementById('result-headline').textContent = found
    ? fixed + ' of ' + found + ' issues verified fixed'
    : 'No visual issues found';
  document.getElementById('result-subline').textContent =
    raw + ' browser findings · ' + rounds + (rounds === 1 ? ' repair round' : ' repair rounds');

  const note = document.getElementById('result-note');
  note.textContent = report.error
    ? 'A proposed repair failed the HTML checks.'
    : report.mock_mode ? 'Fixture run. Results use browser measurements.' : '';
  note.hidden = !note.textContent;

  const fixedUrl = report.fixed_html_url;
  for (const id of ['download-btn', 'open-fixed-btn']) {
    const link = document.getElementById(id);
    link.hidden = !fixedUrl;
    if (fixedUrl) link.href = fixedUrl;
    else link.removeAttribute('href');
  }
  document.getElementById('run-again-btn').hidden = !liveEnabled;

  renderSlider(report);
  renderIssues(report);
  showView('result');
}

function renderSlider(report) {
  const c      = document.getElementById('slider-container');
  const vp     = currentVP;
  const before = (report.before_screenshots         || {})[vp];
  const after  = (report.final_after_screenshots    || {})[vp];
  const vpName = vp === 'desktop' ? 'Desktop' : 'Mobile';
  document.getElementById('result-slider-wrap').setAttribute('aria-labelledby', vp + '-tab');

  document.getElementById('fig-label-before').textContent = vpName + ' · Before';
  document.getElementById('fig-label-after').textContent = vpName + ' · After';
  c.classList.toggle('mobile', vp === 'mobile');
  if (before && after) {
    createSlider(c, before, after, vp);
  } else {
    const message = document.createElement('p');
    message.className = 'empty-comparison';
    message.textContent = before
      ? 'No repaired capture for this viewport.'
      : 'No captures available for this viewport.';
    if (before) {
      const image = new Image();
      image.src = before;
      image.alt = vpName + ' capture of the original page';
      c.replaceChildren(image, message);
    } else {
      c.replaceChildren(message);
    }
  }
}

function renderIssues(report) {
  const tbody = document.getElementById('issue-tbody');
  tbody.innerHTML = '';
  const issues  = report.per_issue     || [];
  const annIss  = report.analysis_issues || [];
  const ignored = report.ignored        || [];

  const annMap = {};
  for (const ai of annIss)
    if (ai.annotation_url && ai.annotation_method !== 'none')
      annMap[ai.id] = location.origin + ai.annotation_url;

  if (issues.length === 0 && ignored.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="padding:16px;color:var(--ink-3)">No issues recorded.</td></tr>';
    return;
  }

  issues.forEach((iss, idx) => {
    const tr = document.createElement('tr');
    tr.className = 'ledger-row';
    if (annMap[iss.id]) {
      tr.classList.add('issue-expandable');
      tr.tabIndex = 0;
      tr.setAttribute('aria-expanded', 'false');
    }
    if (!REDUCED) tr.style.animationDelay = idx * 40 + 'ms';

    const bRaw = iss.dom_before || '—', aRaw = iss.dom_after || '—';
    function shorten(s) {
      if (!s || s === '—') return s;
      s = s.replace('outside viewport (target: inside)', 'outside viewport');
      return s.length > 28 ? s.slice(0, 26) + '…' : s;
    }
    const measure = esc(shorten(bRaw)) + ' → ' + esc(shorten(aRaw));

    const domCls  = iss.dom_signal === 'fixed' ? 'pass' : iss.dom_signal === 'not_fixed' ? 'fail' : 'skip';
    const visCls  = report.mock_mode ? 'skip' : iss.spark_signal ? 'pass' : 'fail';
    const domLabel = { pass: 'DOM passed', fail: 'DOM failed', skip: 'DOM unavailable' }[domCls];
    const visionLabel = report.mock_mode ? 'Fixture' : iss.spark_signal ? 'Vision passed' : 'Vision unconfirmed';
    const stCls = iss.fixed ? 'st-fixed' : 'st-unfixed';
    const stTxt   = iss.fixed ? 'Verified' : 'Not verified';

    tr.innerHTML =
      '<td><span class="issue-num" aria-label="Issue ' + (idx+1) + '">' + (idx+1) + '</span></td>' +
      '<td class="issue-desc">' + esc(iss.description || '') + '</td>' +
      '<td class="issue-measure">' + measure + '</td>' +
      '<td class="issue-checks">' +
        '<span class="check-line ' + domCls + '"><span class="check-dot"></span>' + domLabel + '</span>' +
        '<span class="check-line ' + visCls + '"><span class="check-dot"></span>' + visionLabel + '</span>' +
      '</td>' +
      '<td><span class="status-cell ' + stCls + '"><span class="status-dot"></span>' + stTxt + '</span></td>';

    // Expand on click or Enter/Space
    const expand = () => {
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('expand-row')) {
        next.remove(); tr.setAttribute('aria-expanded','false'); return;
      }
      if (!annMap[iss.id]) return;
      const exp = document.createElement('tr');
      exp.className = 'expand-row';
      exp.innerHTML = '<td colspan="5"><div class="expand-inner">' +
        '<img src="' + annMap[iss.id] + '" alt="Annotated overlay for issue ' + (idx+1) + '" loading="lazy">' +
        '</div></td>';
      tr.after(exp);
      tr.setAttribute('aria-expanded','true');
    };
    tr.addEventListener('click', expand);
    tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); expand(); } });
    tbody.appendChild(tr);
  });

  // Ignored rows (no annotation, low visual weight)
  ignored.forEach(ig => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td><span class="issue-num" style="border-color:var(--ink-3);color:var(--ink-3)">—</span></td>' +
      '<td class="issue-desc" style="color:var(--ink-2)">' + esc(ig.type || '') + ': ' + esc(ig.selector || '') + '</td>' +
      '<td colspan="3" style="color:var(--ink-3);font-size:12px">Ignored · ' + esc(ig.ignore_reason || 'decorative') + '</td>';
    tbody.appendChild(tr);
  });
}

async function toggleRuns() {
  const sec = document.getElementById('saved-runs-section');
  sec.hidden = !sec.hidden;
  document.getElementById('show-runs-btn').setAttribute('aria-expanded', String(!sec.hidden));
  if (!sec.hidden) {
    document.getElementById('saved-runs-heading').focus();
    await loadRuns();
  }
}

async function loadRuns() {
  try {
    const data = await apiFetch('/api/runs');
    const list = document.getElementById('saved-runs-list');
    list.innerHTML = '';
    list.removeEventListener('click', onRunsClick);
    const runs = data.runs || [];
    if (!runs.length) {
      list.innerHTML = '<p style="color:var(--ink-3);font-size:13px;padding:12px 0">No saved runs yet. Complete an analysis first.</p>';
      return;
    }
    for (const run of runs) {
      const div = document.createElement('div');
      div.className = 'run-row' + (run.featured ? ' featured' : '');
      div.dataset.runId = run.run_id;
      div.setAttribute('role','listitem');
      div.setAttribute('tabindex','0');
      let h = '<span class="run-label">' + esc(run.label) + '</span>';
      if (run.featured) h += '<span class="run-featured-mark">Featured</span>';
      h += '<span class="run-acts">' +
           '<button class="run-act-btn" data-action="star" data-site="' + run.site + '" data-rid="' + run.run_id + '">Star</button>' +
           '<button class="run-act-btn" data-action="hide" data-rid="' + run.run_id + '">Hide</button>' +
           '</span>';
      div.innerHTML = h;
      div.addEventListener('keydown', e => { if (e.target === div && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); replayRun(run.run_id); }});
      list.appendChild(div);
    }
    list.addEventListener('click', onRunsClick);
  } catch {
    document.getElementById('saved-runs-list').textContent = 'Could not load saved runs. Try opening the list again.';
  }
}

function onRunsClick(e) {
  const star = e.target.closest('[data-action="star"]');
  const hide = e.target.closest('[data-action="hide"]');
  if (star) { e.stopPropagation(); featureRun(star.dataset.site, star.dataset.rid); }
  else if (hide) { e.stopPropagation(); hideRun(hide.dataset.rid); }
  else { const row = e.target.closest('.run-row'); if (row) replayRun(row.dataset.runId); }
}

async function featureRun(site, runId) {
  await apiFetch('/api/replay', { method:'POST', body: JSON.stringify({ demo: site, run_id: runId }) });
  loadRuns();
}
async function hideRun(runId) {
  await apiFetch('/api/run/' + runId + '/hide', { method:'POST' });
  loadRuns();
}
async function featureCurrent() {
  if (!currentReport) return;
  const report = currentReport;
  const status = document.getElementById('feature-status');
  const button = document.getElementById('feature-btn');
  const path = new URL(report.url, location.origin).pathname;
  const demo = path.match(/^\/demo-sites\/(demo[1-4])\.html$/)?.[1] || 'custom';
  button.disabled = true;
  try {
    await apiFetch('/api/replay', {
      method: 'POST',
      body: JSON.stringify({ demo, run_id: report.run_id })
    });
    if (currentReport === report) status.textContent = 'Run marked as featured.';
  } catch {
    if (currentReport === report) status.textContent = 'Could not feature this run. Try again.';
  } finally {
    button.disabled = false;
  }
}

let diffCache = {};  // runId → diff data

async function renderDiff(report) {
  const panel = document.getElementById('diff-panel');
  const runId = report.run_id;

  // Loading state
  panel.innerHTML = '<div class="diff-empty">Loading diff…</div>';

  let data;
  if (diffCache[runId]) {
    data = diffCache[runId];
  } else {
    try {
      data = await apiFetch('/api/run/' + runId + '/diff');
      diffCache[runId] = data;
    } catch (e) {
      panel.innerHTML = '<div class="diff-empty">' + esc(e.message || 'Could not load diff.') + '</div>';
      return;
    }
  }

  if (currentReport?.run_id !== runId) return;
  if (!data.has_diff || !data.hunks.length) {
    panel.innerHTML = '<div class="diff-empty">No changes detected between original and fixed HTML.</div>';
    return;
  }

  // Build issue index for marker numbers
  const issueNums = {};
  (report.per_issue || []).forEach((iss, i) => { issueNums[iss.id] = i + 1; });

  const linesChanged = data.total_additions + data.total_deletions;
  const rulesNote    = data.rules_changed > 0 ? ' · ~' + data.rules_changed + ' CSS rule' + (data.rules_changed !== 1 ? 's' : '') + ' changed' : '';

  let html = '<div class="diff-summary">'
    + '<span>' + data.total_hunks + ' hunk' + (data.total_hunks !== 1 ? 's' : '') + ' · ' + linesChanged + ' lines changed' + rulesNote + '</span>'
    + '<span class="add">+' + data.total_additions + ' added</span>'
    + '<span class="del">−' + data.total_deletions + ' removed</span>'
    + '</div>';

  data.hunks.forEach((hunk, hi) => {
    const hunkId = 'hunk-' + hi;
    let label = '';
    if (hunk.issue_id && issueNums[hunk.issue_id]) {
      const num = issueNums[hunk.issue_id];
      label = '<span class="hunk-issue-tag"><span class="hunk-issue-marker">' + num + '</span>'
            + esc((hunk.issue_desc || '').slice(0, 60)) + '</span>';
    } else {
      label = '<span class="hunk-other-tag">Other change</span>';
    }

    const header = esc(hunk.header || '');
    const addCount = hunk.lines.filter(l => l.startsWith('+') && !l.startsWith('+++')).length;
    const delCount = hunk.lines.filter(l => l.startsWith('-') && !l.startsWith('---')).length;
    const countNote = '+' + addCount + ' −' + delCount;

    html += '<details class="diff-hunk" open>'
          + '<summary class="hunk-label">'
          + label
          + '<span class="hunk-header-text">' + header + '</span>'
          + '<span class="hunk-toggle">' + countNote + '</span>'
          + '</summary>'
          + '<div class="hunk-code"><pre>';

    hunk.lines.forEach((line, li) => {
      let cls = 'ctx';
      if (line.startsWith('+') && !line.startsWith('+++')) cls = 'add';
      else if (line.startsWith('-') && !line.startsWith('---')) cls = 'del';
      html += '<div class="diff-line ' + cls + '">'
            + '<span class="diff-line-num" aria-hidden="true">' + (li + 1) + '</span>'
            + '<span class="diff-line-content">' + esc(line) + '</span>'
            + '</div>';
    });

    html += '</pre></div></details>';
  });

  panel.innerHTML = html;
}

function showError(msg) {
  console.error('[VisualDetox]', msg);
  showView('error');
  document.getElementById('error-msg').textContent = msg;
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

async function apiFetch(path, opts = {}) {
  const defaults = { headers: { 'Content-Type': 'application/json' } };
  const resp = await fetch(location.origin + path, { ...defaults, ...opts });
  if (!resp.ok) { const t = await resp.text(); throw new Error(t); }
  return resp.json();
}
