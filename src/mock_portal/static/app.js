/* 発注管理 mock — rendering and the row -> detail -> note -> commit motif.
 *
 * The automation drives this page exactly the way the logs show an operator
 * driving the real one: click the row's 氏名 cell, focus #rt-note, write, click
 * #btn-rt-ok. Nothing here is aware that an automation exists.
 */

// Compact mode for when this page is embedded next to the review UI. It only
// hides the left nav and tightens the table so the ステータス column is visible in a
// narrow frame — the MOCK banner, the values and the DOM contract are untouched.
const EMBED = new URLSearchParams(location.search).get('embed') === '1';
if (EMBED) {
  document.body.classList.add('embed');
}

let STATE = null;
let SELECTED = null;   // case_id
let REV = null;        // the portal revision this page has rendered
let PREV_STATUS = {};  // case_id -> the ステータス this page last painted

async function load() {
  const r = await fetch('/api/state', { cache: 'no-store' });
  STATE = await r.json();
  REV = STATE.rev;
  // Stamp the serving process onto the DOM. The automation reads this out of the
  // rendered page, so its audit record proves which portal the BROWSER actually
  // reached — not which one anybody intended it to reach.
  document.body.dataset.portalEpoch = STATE.epoch || '';
  document.body.dataset.portalServer = STATE.server_id || '';
  render();
}

function render() {
  const tbody = document.querySelector('#rt-table > tbody');
  tbody.innerHTML = '';

  const painted = {};
  let firstChanged = null;

  STATE.cases.forEach((c) => {
    const tr = document.createElement('tr');
    if (c.case_id === SELECTED) tr.classList.add('selected');
    const cells = c.row_cells;
    // Did this row's ステータス move since the last paint? Only true on a repaint
    // that followed a real commit, so it is the cue the reviewer is watching for.
    const flipped = PREV_STATUS[c.case_id] !== undefined
                 && PREV_STATUS[c.case_id] !== cells.status;
    painted[c.case_id] = cells.status;
    [cells.id, cells.emp_id, cells.name, cells.kubun,
     cells.amount, cells.shubetsu, cells.status].forEach((val, i) => {
      const td = document.createElement('td');
      td.textContent = val;
      if (i === 6) {
        td.className = 'st st-' + statusClass(val);
        if (flipped) td.classList.add('flip');
      }
      if (i === 5 && val !== '定常' && val !== '調整') {
        td.className = 'odd';
      }
      tr.appendChild(td);
    });
    if (flipped) {
      tr.classList.add('flip-row');
      if (firstChanged === null) firstChanged = tr;
    }
    // The operator opens a case by clicking the 氏名 cell (td:nth-of-type(3)).
    // All 66 row-open clicks recovered from dataset B's resident-tax route
    // land on td:nth-of-type(3).
    tr.children[2].addEventListener('click', () => select(c.case_id));
    tbody.appendChild(tr);
  });
  PREV_STATUS = painted;
  // In a 700px frame beside the review UI the row that just changed may be below
  // the fold. Bring it into view — inside this frame only, so the page around it
  // does not move under the reviewer.
  if (EMBED && firstChanged) {
    firstChanged.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  const pending = STATE.cases.filter((c) => c.row_cells.status === '未処理').length;
  document.querySelector('#case-count').textContent =
    `${STATE.cases.length} 件 · ${pending} 件未処理`;
  document.querySelector('#nav-count').textContent = STATE.cases.length;

  renderDetail();
  document.querySelector('#rt-toast').textContent = STATE.toast || '';
}

function statusClass(s) {
  return { '未処理': 'pending', '登録済み': 'done', '完了': 'closed',
           '照合中': 'checking', '未確認': 'unconfirmed' }[s] || 'other';
}

function renderDetail() {
  const c = STATE.cases.find((x) => x.case_id === SELECTED);
  const pane = document.querySelector('#rt-detail');
  document.querySelector('#rt-detail-id').textContent = c ? c.case_id : '—';
  const badge = document.querySelector('#rt-detail-status');
  badge.textContent = c ? c.row_cells.status : '—';
  badge.className = 'badge ' + (c ? 'st-' + statusClass(c.row_cells.status) : '');

  pane.querySelectorAll('[data-field]').forEach((el) => {
    const k = el.getAttribute('data-field');
    el.textContent = c ? (c.detail[k] || '') : '';
    el.classList.toggle('empty', !!c && !c.detail[k]);
  });

  const note = document.querySelector('#rt-note');
  if (c && c.detail.comment) note.value = c.detail.comment;
}

function select(caseId) {
  SELECTED = caseId;
  document.querySelector('#rt-note').value = '';
  render();
}

document.querySelector('#btn-rt-ok').addEventListener('click', async () => {
  if (!SELECTED) {
    document.querySelector('#rt-toast').textContent = '行が選択されていません';
    return;
  }
  const note = document.querySelector('#rt-note').value;
  const r = await fetch('/api/commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_id: SELECTED, note }),
  });
  await r.json();
  await load();          // the row's status cell now reflects the server's decision
});

load();

// --- live refresh, embedded copy only ------------------------------------
//
// The automation drives this portal in its OWN browser, so a copy of this screen
// embedded beside the review UI learns nothing from that: it would keep showing
// whatever it fetched at first render until somebody reloaded it by hand. That is
// the stale-frame bug — the row really had flipped 未処理 → 登録済み on the server,
// and this frame was still drawing the snapshot it took before the run started.
//
// So the embedded copy watches /api/rev, which is a few dozen bytes, and re-reads
// the worklist ONLY when the server says its state moved. An idle portal is never
// repainted, so there is nothing to flicker; a run repaints once per commit, which
// is what makes the rows flip one at a time as the engine works through them.
//
// The standalone page — the one the engine drives — is deliberately left alone:
// it must not have rows rebuilt underneath a click it is in the middle of making.
if (EMBED) {
  const POLL_MS = 400;

  async function watchPortal() {
    try {
      // Nobody is looking — do not even ask. The next visible tick picks up
      // everything that happened meanwhile, because rev only moves forward.
      if (document.hidden) { setTimeout(watchPortal, POLL_MS); return; }
      const r = await fetch('/api/rev', { cache: 'no-store' });
      const probe = await r.json();
      // An epoch change means RESET DEMO reseeded the worklist; a rev change means
      // a commit landed. Either way what is on screen is out of date.
      if (STATE && (probe.rev !== REV || probe.epoch !== STATE.epoch)) {
        if (probe.epoch !== STATE.epoch) PREV_STATUS = {};   // new worklist, no flips
        await load();
      }
    } catch (e) {
      // Portal restarting, or the frame is being torn down. Ask again next tick.
    }
    setTimeout(watchPortal, POLL_MS);
  }

  setTimeout(watchPortal, POLL_MS);
}
