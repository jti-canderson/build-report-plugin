/*
 * The build screen for /test-report (served only by serve_builder.py --jobs).
 *
 * It replaces the form in place - no navigation - and follows ONE job: a server-sent
 * event stream of full snapshots, with polling as the fallback, so a refresh, a closed
 * laptop or a dropped connection comes back to the same state. The job id and its token
 * live in the URL hash (and localStorage), which is what makes a refresh reattach.
 *
 * Nothing here decides progress. The percent is whatever the server says, and the server
 * only moves it when a stage is reported DONE.
 */
(function () {
  const { useState, useEffect, useRef } = React;
  const html = htm.bind(React.createElement);

  const KEY = 'jti-test-report-job';
  function remember(job) {
    try { job ? localStorage.setItem(KEY, JSON.stringify(job)) : localStorage.removeItem(KEY); }
    catch (e) { /* private window: the hash still carries it */ }
    if (job) history.replaceState(null, '', '#job=' + job.id + '&t=' + encodeURIComponent(job.token));
    else history.replaceState(null, '', location.pathname);
  }
  function recall() {
    const m = /[#&]job=([0-9a-f]{16})&t=([^&]+)/.exec(location.hash);
    if (m) return { id: m[1], token: decodeURIComponent(m[2]) };
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; }
  }

  const TERMINAL = ['complete', 'failed', 'cancelled', 'timed_out'];
  const HEADLINE = {
    submitted: 'Waiting for Claude to pick this up',
    running: 'Building',
    waiting: 'Waiting for your answer',
    cancelling: 'Cancelling…',
    complete: 'Report built and verified',
    failed: 'The build failed',
    cancelled: 'Cancelled',
    timed_out: 'Timed out waiting for an answer',
  };

  function useJob(job) {
    const [snap, setSnap] = useState(null);
    const [conn, setConn] = useState('connecting');
    useEffect(() => {
      if (!job) return;
      let alive = true, es = null, poll = null, fails = 0;
      const url = '/api/jobs/' + job.id;
      const q = '?t=' + encodeURIComponent(job.token);
      const take = d => { if (alive && d) setSnap(d); };
      const startPoll = () => {
        if (poll) return;
        setConn('polling');
        const tick = () => fetch(url + q).then(r => r.ok ? r.json() : Promise.reject(r.status))
          .then(d => { take(d.job); if (TERMINAL.includes(d.job.status)) clearInterval(poll); })
          .catch(code => { if (code === 403 || code === 404) setConn('gone'); });
        tick(); poll = setInterval(tick, 2000);
      };
      if (window.EventSource) {
        es = new EventSource(url + '/events' + q);
        es.addEventListener('snapshot', e => {
          fails = 0; setConn('live');
          const d = JSON.parse(e.data); take(d);
          if (TERMINAL.includes(d.status)) es.close();
        });
        es.onerror = () => {
          // EventSource retries by itself; after a few failures in a row, poll instead.
          if (++fails >= 3) { es.close(); startPoll(); } else setConn('reconnecting');
        };
      } else startPoll();
      return () => { alive = false; if (es) es.close(); if (poll) clearInterval(poll); };
    }, [job && job.id]);
    return [snap, conn, setSnap];
  }

  function Checklist({ stages, snap }) {
    return html`<ol class="bchk">
      ${stages.filter(s => s.key !== 'submitted').map(s => {
        const done = snap.done.includes(s.key);
        const now = !done && snap.stage === s.key && snap.running;
        const failed = snap.failure && snap.failure.stage === s.key;
        return html`<li key=${s.key} class=${done ? 'ok' : failed ? 'bad' : now ? 'now' : ''}>
          <span class="mk">${done ? '✓' : failed ? '✕' : now ? html`<span class="spin1"/>` : '·'}</span>
          ${s.label}<span class="pc">${s.percent}%</span></li>`;
      })}
    </ol>`;
  }

  function FailurePanel({ snap }) {
    const f = snap.failure;
    return html`<div class="bpanel bad">
      <h3>Failed at: ${f.label}</h3>
      <p>${f.message}</p>
      <p class="note">${f.auto_attempts
        ? `Claude tried ${f.auto_attempts} automatic fix${f.auto_attempts > 1 ? 'es' : ''} first. `
        : ''}${f.retryable
        ? 'Automatic retry: possible - submitting the same specification again may succeed.'
        : 'Automatic retry: no - this needs a change before it can build.'}</p>
      ${f.excerpt && html`<details open><summary>Log excerpt</summary><pre class="blog">${f.excerpt}</pre></details>`}
      <p class="note">No download is offered: the package was not verified.</p>
      ${snap.partial && snap.partial.length > 0 && html`
        <p class="note">Files this build created (left in place): ${snap.partial.join(', ')}</p>`}
    </div>`;
  }

  // One question from Claude. The job waits on the server until this is answered, so the
  // page can be closed and reopened - the question is part of the job's saved state.
  function QuestionPanel({ job, q }) {
    const [value, setValue] = useState('');
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    const post = (path, body, headers) => {
      setBusy(true); setErr('');
      return fetch('/api/jobs/' + job.id + path, { method: 'POST', body,
        headers: { 'X-JTI-Job': job.token, ...headers } })
        .then(r => r.json()).then(d => { setBusy(false); if (!d.ok) setErr(d.message); })
        .catch(() => { setBusy(false); setErr('Could not reach the builder - try again.'); });
    };
    const send = extra => post('/answer', JSON.stringify({ id: q.id, value, text, ...extra }),
                               { 'Content-Type': 'application/json' });
    const sendFile = e => {
      const f = e.target.files && e.target.files[0];
      if (f) post('/upload?q=' + encodeURIComponent(q.id), f,
                  { 'X-JTI-Filename': encodeURIComponent(f.name) });
    };
    const until = new Date(q.deadline * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return html`<div class="bpanel ask">
      <h3>${q.title}</h3>
      <p class="qprompt">${q.prompt}</p>
      ${q.type === 'choice' && html`<div class="qopts">
        ${q.options.map(o => html`<label key=${o.value}>
          <input type="radio" name=${'q-' + q.id} checked=${value === o.value}
                 onChange=${() => setValue(o.value)}/>
          <span><b>${o.label}</b>${o.detail && html` <span class="note">${o.detail}</span>`}</span></label>`)}
        ${q.allowText && html`<input type="text" placeholder="Or type your own answer"
              value=${text} onInput=${e => setText(e.target.value)}/>`}</div>`}
      ${q.type === 'text' && html`<input type="text" maxLength="400" value=${text}
              onInput=${e => setText(e.target.value)}/>`}
      ${q.type === 'longtext' && html`<textarea maxLength="20000" value=${text}
              onInput=${e => setText(e.target.value)}/>`}
      ${q.type === 'file' && html`<${React.Fragment}>
        <input type="file" disabled=${busy} onChange=${sendFile}/>
        ${q.options.length > 0 && html`<div class="actions">${q.options.map(o => html`
          <button key=${o.value} class="mini" disabled=${busy}
                  onClick=${() => post('/answer', JSON.stringify({ id: q.id, value: o.value }),
                                       { 'Content-Type': 'application/json' })}>${o.label}</button>`)}</div>`}
      <//>`}
      <div class="actions mt12">
        ${q.type !== 'file' && html`<button class="go sm" disabled=${busy ||
            (q.type === 'choice' ? !value && !(q.allowText && text.trim()) : !text.trim())}
            onClick=${() => send()}>${busy ? 'Sending…' : 'Send answer'}</button>`}
        ${!q.required && html`<button class="mini" disabled=${busy}
            onClick=${() => send({ skip: true })}>Skip</button>`}
        ${busy && q.type === 'file' && html`<span class="note">Uploading…</span>`}
      </div>
      ${err && html`<p class="note warnline">${err}</p>`}
      <p class="note">The build is paused until you answer (it waits until ${until}). You can
        close this page and come back.</p>
    </div>`;
  }

  function BuildScreen({ job, stages, onAnother }) {
    const [snap, conn] = useJob(job);
    if (conn === 'gone' && !snap) return html`<div class="bpanel bad"><h3>This build is no longer
      available</h3><p>The link is out of date or the job was removed.</p>
      <button class="go sm" onClick=${onAnother}>Build another report</button></div>`;
    if (!snap) return html`<div class="spin">Connecting to the build…</div>`;
    const term = TERMINAL.includes(snap.status);
    const stageLabel = (stages.find(s => s.key === snap.stage) || {}).label || snap.stage;
    const stale = snap.status === 'running' && snap.worker_seen_ago > 180;
    return html`<div class="build">
      <div class="bhead">
        <div>
          <div class="bname">${snap.report.title || snap.report.name}</div>
          <div class="note">Saving to: <code>${snap.report.folder}</code></div>
        </div>
        <div class=${'bstate ' + snap.status}>${HEADLINE[snap.status] || snap.status}</div>
      </div>

      <div class="bbar"><div class="fill" style=${{ width: snap.percent + '%' }}/></div>
      <div class="bnow">
        ${!term && snap.running && html`<span class="spin1"/>`}
        <b>${snap.percent}%</b>
        <span>${term ? '' : stageLabel}</span>
        <span class="note">${snap.status_text}</span>
      </div>
      ${snap.status === 'submitted' && html`<p class="note">${snap.worker_waiting
        ? 'Claude is ready and will start in a moment.'
        : 'No Claude session is waiting yet. The build starts as soon as /test-report is running.'}</p>`}
      ${stale && html`<p class="note warnline">No word from Claude for
        ${Math.round(snap.worker_seen_ago / 60)} min - it may be working on a long step.</p>`}
      ${conn !== 'live' && !term && html`<p class="note">Connection: ${conn}</p>`}

      ${snap.question && html`<${QuestionPanel} key=${snap.question.id + snap.question.asked}
                                    job=${job} q=${snap.question}/>`}
      ${snap.status === 'failed' && html`<${FailurePanel} snap=${snap}/>`}
      ${snap.status === 'timed_out' && html`<div class="bpanel bad"><h3>Timed out</h3>
        <p>The build waited for an answer${snap.timed_out && snap.timed_out.title
          ? ' to "' + snap.timed_out.title + '"' : ''} that did not come, and stopped. Nothing was
          deleted.${snap.partial && snap.partial.length ? ' Files it had created: ' + snap.partial.join(', ') : ''}</p></div>`}
      ${snap.status === 'cancelled' && html`<div class="bpanel"><h3>Cancelled</h3>
        <p>Nothing was deleted.${snap.partial && snap.partial.length
          ? ' Files this build had created: ' + snap.partial.join(', ') : ' This build created no files.'}</p></div>`}

      <${Checklist} stages=${stages} snap=${snap}/>

      <details class="mt12"><summary>Technical log (${snap.log_tail.length} recent lines)</summary>
        <pre class="blog">${snap.log_tail.join('\n') || '(nothing yet)'}</pre></details>

      ${term && html`<div class="mt12"><button class="go sm" onClick=${onAnother}>Build another report</button></div>`}
    </div>`;
  }

  window.JTIBuild = { BuildScreen, remember, recall };
})();
