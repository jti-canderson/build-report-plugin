/*
 * The build screen for /build-report (served only by serve_builder.py --jobs).
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

  const KEY = 'jti-build-report-job';
  function remember(job) {
    try { job ? localStorage.setItem(KEY, JSON.stringify(job)) : localStorage.removeItem(KEY); }
    catch (e) { /* private window: the hash still carries it */ }
    if (job) history.replaceState(null, '', '#job=' + job.id + '&t=' + encodeURIComponent(job.token));
    else history.replaceState(null, '', location.pathname);
  }
  /** {id, token, linked}: `linked` when the ADDRESS names the job (a reload of that tab, or
   * a link opened on purpose) - shown whatever its state. One only remembered from an
   * earlier visit is shown only while it is still running: a finished build must not greet
   * the next /build-report as if the form were already filled in. */
  function recall() {
    const m = /[#&]job=([0-9a-f]{16})&t=([^&]+)/.exec(location.hash);
    if (m) return { id: m[1], token: decodeURIComponent(m[2]), linked: true };
    try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; }
  }
  function forget() { try { localStorage.removeItem(KEY); } catch (e) { /* nothing kept */ } }

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

  function useJob(job, round) {
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
    }, [job && job.id, round]);
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
          ${failed ? s.name + ' - failed' : s.label}<span class="pc">${s.percent}%</span></li>`;
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

  const KIND = { rule: 'Rule source', jrxml: 'Report layout', 'rule-zip': 'Rule ZIP (import this)',
                 doc: 'Document', pdf: 'Rendered PDF', page: 'Page image',
                 launcher: 'Launcher (static-text Velocity)' };
  function CompletePanel({ job, snap, onAnother }) {
    const t = '?t=' + encodeURIComponent(job.token);
    const base = '/api/jobs/' + job.id;
    const pages = snap.artifacts.filter(a => a.kind === 'page');
    const files = snap.artifacts.filter(a => a.kind !== 'page');
    return html`<div class="bpanel done">
      <h3>Built and verified</h3>
      <p>Saved in: <code>${snap.report.folder}</code></p>
      ${pages.length > 0 && html`<div class="thumbs">${pages.map(a => html`
        <a key=${a.id} href=${base + '/preview/' + a.id + t} target="_blank" rel="noopener">
          <img src=${base + '/preview/' + a.id + t} alt=${a.name}/><div class="cap">${a.name}</div></a>`)}</div>`}
      <p class="note mt12">Look at every page before you import - the gates prove the layout
        compiles and fills, not that it is right.</p>
      <div class="actions mt12">
        <a class="go sm" href=${base + '/package' + t} download>Download a copy (report package)</a>
        <button class="mini" onClick=${onAnother}>Build another report</button>
      </div>
      <ul class="arts">${files.map(a => html`<li key=${a.id}><span class="k">${KIND[a.kind] || a.kind}</span>
        <code>${a.rel}</code><span class="note">${Math.max(1, Math.round(a.bytes / 1024))} KB</span>
        <a href=${base + '/file/' + a.id + t} download>Download</a></li>`)}</ul>
      <p class="note">Downloads are copies: the report itself stays in the folder above. Your
        browser decides where a download is saved (usually Downloads).</p>
      <p class="note"><b>Importing is a write.</b> Import the rule ZIP into eSeries yourself.</p>
    </div>`;
  }

  // After a build: ASK about the report (answered in words, nothing changes) or REQUEST a
  // change (Claude changes THIS report, re-runs every gate and completes it again).
  const MAX_ATTACH = 6;
  const ACCEPT = 'image/png,image/jpeg,image/gif,image/webp,.pdf,.zip,.xlsx,.xls,.docx,.doc,.pptx,'
    + '.txt,.csv,.tsv,.json,.xml,.jrxml,.groovy,.vm,.md,.log,.sql,.html,.htm,.yaml,.yml,.properties';
  function attachNote(q) {
    const n = (q.images || []).length, f = (q.files || []).length;
    const parts = [n && n + ' picture' + (n > 1 ? 's' : ''), f && f + ' file' + (f > 1 ? 's' : '')].filter(Boolean);
    return parts.length ? html` <span class="note">(with ${parts.join(' and ')})</span>` : '';
  }
  function RevisePanel({ job, snap, onSent, onSnap }) {
    const [text, setText] = useState('');
    const [busy, setBusy] = useState('');
    const [err, setErr] = useState('');
    const [pics, setPics] = useState([]);          // attachments: {key, kind, name, url, id, err}
    const [drag, setDrag] = useState(false);
    const picker = useRef(null);
    const past = snap.revisions || [];
    const asked = snap.inquiries || [];
    const uploading = pics.some(p => !p.id && !p.err);
    const count = useRef(0);                       // attachments held, including ones still uploading
    count.current = pics.length;
    // Pasted, dropped or picked: each file is uploaded to this job's folder and goes to Claude
    // with the message. Pictures go as pictures; anything else needs a name the server accepts.
    const addFiles = files => {
      files.filter(Boolean).forEach(f => {
        if (count.current >= MAX_ATTACH) { setErr('Up to ' + MAX_ATTACH + ' attachments per message.'); return; }
        count.current += 1;
        const key = Math.random().toString(36).slice(2);
        const img = /^image\/(png|jpeg|gif|webp)$/.test(f.type);
        const name = f.name || (img ? 'screenshot' : 'file');
        setPics(ps => [...ps, { key, kind: img ? 'image' : 'file', name, url: img ? URL.createObjectURL(f) : '' }]);
        const headers = { 'X-JTI-Job': job.token, 'Content-Type': img ? f.type : 'application/octet-stream' };
        if (!img || f.name) headers['X-JTI-Name'] = encodeURIComponent(name);
        fetch('/api/jobs/' + job.id + '/attach', { method: 'POST', body: f, headers })
          .then(r => r.json()).then(d => setPics(ps => ps.map(p => p.key !== key ? p
            : d.ok ? { ...p, id: d.id, kind: d.kind || p.kind } : { ...p, err: d.message || 'Could not add that file.' })))
          .catch(() => setPics(ps => ps.map(p => p.key === key ? { ...p, err: 'Could not reach the builder.' } : p)));
      });
    };
    // Text pastes are left alone; a pasted picture or file is attached.
    const onPaste = e => {
      const files = [...((e.clipboardData && e.clipboardData.items) || [])]
        .filter(it => it.kind === 'file').map(it => it.getAsFile()).filter(Boolean);
      if (!files.length) return;
      e.preventDefault();
      addFiles(files);
    };
    const onDrop = e => {
      e.preventDefault(); setDrag(false);
      addFiles([...((e.dataTransfer && e.dataTransfer.files) || [])]);
    };
    // The button reads the clipboard directly (the browser asks permission the first time).
    const fromClipboard = async () => {
      setErr('');
      if (!navigator.clipboard || !navigator.clipboard.read) {
        setErr('This browser cannot read the clipboard from a button - click in the box and press ⌘V / Ctrl+V.');
        return;
      }
      try {
        const items = await navigator.clipboard.read();
        const files = [];
        for (const it of items) {
          const type = it.types.find(x => /^image\//.test(x));
          if (type) { const b = await it.getType(type); files.push(new File([b], 'screenshot.' + (type.split('/')[1] || 'png'), { type })); }
        }
        if (!files.length) { setErr('There is no picture on the clipboard. Copy a screenshot first (⌘⇧⌃4 on a Mac copies one).'); return; }
        addFiles(files);
      } catch (x) {
        setErr('The browser did not allow reading the clipboard - click in the box and press ⌘V / Ctrl+V instead.');
      }
    };
    const drop = key => setPics(ps => ps.filter(p => { if (p.key === key && p.url) URL.revokeObjectURL(p.url); return p.key !== key; }));
    const waiting = asked.some(q => q.answer == null);
    // The event stream ends with a finished job, so poll while a question is open.
    useEffect(() => {
      if (!waiting) return;
      const t = setInterval(() => fetch('/api/jobs/' + job.id + '?t=' + encodeURIComponent(job.token))
        .then(r => r.ok ? r.json() : null).then(d => { if (d && d.job) onSnap(d.job); }).catch(() => {}), 2500);
      return () => clearInterval(t);
    }, [waiting, job.id]);
    const send = kind => {
      setBusy(kind); setErr('');
      fetch('/api/jobs/' + job.id + (kind === 'ask' ? '/inquire' : '/revise'), { method: 'POST',
        body: JSON.stringify({ text, images: pics.filter(p => p.id && p.kind === 'image').map(p => p.id),
                               files: pics.filter(p => p.id && p.kind === 'file').map(p => p.id) }),
        headers: { 'X-JTI-Job': job.token, 'Content-Type': 'application/json' } })
        .then(r => r.json()).then(d => {
          setBusy('');
          if (!d.ok) { setErr(d.message || 'Could not send that.'); return; }
          setText(''); pics.forEach(p => p.url && URL.revokeObjectURL(p.url)); setPics([]);
          if (kind === 'ask') onSnap(d.job); else onSent(d.job);
        })
        .catch(() => { setBusy(''); setErr('Could not reach the builder - try again.'); });
    };
    return html`<div class="bpanel revise">
      <h3>Questions or changes?</h3>
      <p class="note">Ask anything about this report - where a column comes from, what a filter
        does, why something prints the way it does - and Claude answers here without changing
        anything. Or describe a change, and Claude changes this report and verifies it again; the
        files above are replaced when it passes.</p>
      ${asked.length > 0 && html`<div class="thread">${asked.map(q => html`<div key=${q.n} class="qa">
        <div class="q"><b>You asked</b> ${q.text}${attachNote(q)}</div>
        <div class=${'a' + (q.answer == null ? ' pending' : '')}>${q.answer == null
          ? html`<span class="spin1"/> Claude is looking into it…` : html`<b>Claude</b> ${q.answer}`}</div></div>`)}</div>`}
      <textarea maxLength="20000" class=${drag ? 'drag' : ''}
                placeholder="e.g. Where does the Courtroom column come from?  or  Add the filing date after the case number. Paste a screenshot or drop a file here if it helps."
                value=${text} onInput=${e => setText(e.target.value)} onPaste=${onPaste}
                onDragOver=${e => { e.preventDefault(); setDrag(true); }} onDragLeave=${() => setDrag(false)} onDrop=${onDrop}/>
      ${pics.length > 0 && html`<div class="pics">${pics.map(p => html`<div key=${p.key} class=${'pic' + (p.err ? ' bad' : '')}>
        ${p.kind === 'image' && p.url ? html`<img src=${p.url} alt="pasted screenshot"/>`
          : html`<div class="file" title=${p.name}><span class="ext">${(p.name.split('.').pop() || 'file').slice(0, 5)}</span><span class="fname">${p.name}</span></div>`}
        <button class="x" title="Remove" onClick=${() => drop(p.key)}>×</button>
        <div class="cap">${p.err || (p.id ? 'Added' : 'Adding…')}</div></div>`)}</div>`}
      <div class="attachbar">
        <button class="mini" type="button" onClick=${() => picker.current && picker.current.click()}>Attach a file…</button>
        <button class="mini" type="button" onClick=${fromClipboard}>Paste from clipboard</button>
        <input ref=${picker} type="file" multiple hidden accept=${ACCEPT}
               onChange=${e => { addFiles([...e.target.files]); e.target.value = ''; }}/>
        <span class="note">Or paste (⌘V / Ctrl+V) or drop into the box. Pictures, PDF, Word, Excel, zip or
          text files, up to ${MAX_ATTACH} per message, 10 MB each.</span>
      </div>
      <div class="actions mt12">
        <button class="go sm" disabled=${!!busy || !text.trim() || waiting || uploading}
                onClick=${() => send('ask')}>${busy === 'ask' ? 'Sending…' : 'Ask a question'}</button>
        <button class="mini" disabled=${!!busy || !text.trim() || uploading}
                onClick=${() => send('change')}>${busy === 'change' ? 'Sending…' : 'Request changes'}</button>
        <span class="note">If no Claude session is waiting, it starts the next time /build-report runs.</span>
      </div>
      ${err && html`<p class="note warnline">${err}</p>`}
      ${past.length > 0 && html`<details class="mt12"><summary>Earlier change requests (${past.length})</summary>
        <ol class="revs">${past.map(r => html`<li key=${r.n}>${r.text}</li>`)}</ol></details>`}
    </div>`;
  }

  function BuildScreen({ job, stages, onAnother }) {
    const [round, setRound] = useState(0);
    const [snap, conn, setSnap] = useJob(job, round);
    if (conn === 'gone' && !snap) return html`<div class="bpanel bad"><h3>This build is no longer
      available</h3><p>The link is out of date or the job was removed.</p>
      <button class="go sm" onClick=${onAnother}>Build another report</button></div>`;
    if (!snap) return html`<div class="spin">Connecting to the build…</div>`;
    const term = TERMINAL.includes(snap.status);
    // While a stage runs (or waits on a question) show what is being DONE; once it is done,
    // its completed label. The checklist always uses the completed labels.
    const st = stages.find(s => s.key === snap.stage) || {};
    const stageLabel = snap.done.includes(snap.stage) ? st.label : (st.doing || st.label || snap.stage);
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
        : 'No Claude session is waiting yet. The build starts as soon as /build-report is running.'}</p>`}
      ${stale && html`<p class="note warnline">No word from Claude for
        ${Math.round(snap.worker_seen_ago / 60)} min - it may be working on a long step.</p>`}
      ${conn !== 'live' && !term && html`<p class="note">Connection: ${conn}</p>`}

      ${snap.question && html`<${QuestionPanel} key=${snap.question.id + snap.question.asked}
                                    job=${job} q=${snap.question}/>`}
      ${snap.status === 'complete' && html`<${CompletePanel} job=${job} snap=${snap} onAnother=${onAnother}/>`}
      ${snap.status === 'complete' && html`<${RevisePanel} job=${job} snap=${snap} onSnap=${setSnap}
            onSent=${d => { if (d) setSnap(d); setRound(r => r + 1); }}/>`}
      ${snap.revision && !term && html`<div class="bpanel"><h3>Making your changes (round ${snap.revision.n})</h3>
        <p class="qprompt">${snap.revision.text}</p>${(snap.revision.images || []).length > 0
          && html`<p class="note">With ${snap.revision.images.length} pasted picture${snap.revision.images.length > 1 ? 's' : ''}.</p>`}</div>`}
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

      ${!term && html`<div class="mt12"><button class="mini" disabled=${snap.status === 'cancelling'}
            onClick=${() => { if (confirm('Cancel this build? Files it already created are kept.'))
              fetch('/api/jobs/' + job.id + '/cancel', { method: 'POST', body: '{}',
                headers: { 'X-JTI-Job': job.token, 'Content-Type': 'application/json' } }); }}>
            ${snap.status === 'cancelling' ? 'Cancelling…' : 'Cancel build'}</button></div>`}
      ${term && snap.status !== 'complete' && html`<div class="mt12"><button class="go sm"
            onClick=${onAnother}>Build another report</button></div>`}
    </div>`;
  }

  window.JTIBuild = { BuildScreen, remember, recall, forget, TERMINAL };
})();
