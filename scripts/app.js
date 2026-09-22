/*
 * JTI Report Builder — one React app, no build step.
 *
 * React + ReactDOM + htm are vendored in scripts/vendor/, so this needs no npm, no bundler
 * and no internet. htm gives JSX-like syntax inside tagged template literals, which is why
 * there is no Babel either: the browser parses this file as it stands.
 *
 * Everything is one screen with no navigation. Adding a section, browsing for a folder and
 * showing the result all mutate state in place - nothing here reloads or changes pages.
 */
const { useState, useEffect, useCallback } = React;
const html = htm.bind(React.createElement);

const TYPES = [
  ['java.lang.String', 'Text'],
  ['java.util.Date', 'Date'],
  ['java.lang.Integer', 'Whole number'],
];
// "None of these - here is a picture of what I want." Not a template module: it is the
// absence of one, and the server turns it into a spec with no template and a reference
// image beside it, which /build-report reads and starts from the nearest match.
const PICTURE = '__picture__';
const uid = (() => { let n = 0; return () => ++n; })();
const newCol = () => ({ id: uid(), header: '', width: 20, align: 'Left', field: '' });
const newSection = () => ({ id: uid(), key: '', title: '', cols: [newCol(), newCol()] });
const newParam = () => ({ id: uid(), name: '', type: TYPES[0][0] });

/* ---------------------------------------------------------------- folder browser */
function FolderBrowser({ onPick, onClose }) {
  const [at, setAt] = useState(null);
  const [err, setErr] = useState('');
  const [typed, setTyped] = useState('');
  const load = useCallback(p => {
    fetch('/api/browse?path=' + encodeURIComponent(p || ''))
      .then(r => r.json())
      .then(d => {
        if (d.error) {
          // Put the ATTEMPTED path in the box, not the last one that worked. The error
          // tells the user they can still pick it with "Use this path" - which would have
          // silently picked the previous folder instead if the box had not been updated.
          setErr(d.error);
          if (p) setTyped(p);
          return;
        }
        setErr(''); setAt(d); setTyped(d.label);
      });
  }, []);
  useEffect(() => { load(''); }, [load]);

  // Choose a folder WITHOUT listing it. Reading ~/Desktop or ~/Documents is what triggers
  // the macOS privacy prompt, and browsing is not choosing - the prompt belongs at the
  // moment something is written, not when someone clicks a suggestion.
  const usePath = () => {
    fetch('/api/checkdir?path=' + encodeURIComponent(typed))
      .then(r => r.json())
      .then(d => {
        if (!d.ok) return setErr(d.message);
        if (!d.pickable) return setErr('That folder is itself a report — pick its parent.');
        onPick(d.inside && d.path === d.root ? '.' : d.path);
        onClose();
      });
  };

  if (!at) return html`<div class="modal"><div class="sheet">
    ${err ? html`<div class="out err" style="margin:16px">${err}</div>` : html`<div class="spin">Loading…</div>`}
  </div></div>`;

  return html`
    <div class="modal" onClick=${e => e.target.classList.contains('modal') && onClose()}>
      <div class="sheet">
        <h3>Choose a folder</h3>
        <div class="quick">
          ${at.quick.map(q => html`
            <button key=${q.name} title=${q.path}
                    class=${'mini' + (at.label === q.path ? ' on' : '')}
                    onClick=${() => load(q.path)}>${q.name}</button>`)}
        </div>
        <div class="quick">
          <input type="text" value=${typed} spellcheck="false"
                 onInput=${e => setTyped(e.target.value)}
                 onKeyDown=${e => e.key === 'Enter' && load(typed)}/>
          <button class="mini" onClick=${() => load(typed)}>Open</button>
          <button class="mini" onClick=${usePath}>Use this path</button>
        </div>
        <div class="pathnote">Shortcuts and <b>Open</b> show a folder's contents.
          <b>Use this path</b> picks a folder <i>without</i> reading it — useful when macOS
          blocks the listing, since writing may still be allowed.</div>
        ${!at.inside && html`
          <div class="warn">Outside the workspace (<code>${at.root}</code>). That is allowed
            — the report will be written here — but it will not appear in the project list.</div>`}
        ${err && html`<div class="warn err2">${err}
          ${' '}You can still choose it with <b>Use this path</b> — that does not read the
          folder, so macOS will only ask when the report is written.</div>`}
        <div class="body">
          ${at.parent !== null && html`
            <button class="dir" onClick=${() => load(at.parent)}>
              <span class="n">↑ up one level</span></button>`}
          ${at.dirs.length === 0 && html`<div class="crumb">No sub-folders here.</div>`}
          ${at.dirs.map(d => html`
            <button class=${'dir' + (d.pickable ? '' : ' taken')} key=${d.rel}
                    onClick=${() => load(d.rel)}>
              <span class="n">${d.name}</span>
              ${d.pickable
                ? html`<span class="m">${d.reports
                    ? d.reports + ' report' + (d.reports === 1 ? '' : 's') : 'empty'}</span>`
                : html`<span class="m">already a report</span>`}
            </button>`)}
        </div>
        <div class="foot">
          <span class="note">
            ${at.pickable
              ? 'Builds land in a new folder inside whichever folder you choose.'
              : 'This folder already holds a report, so a new one cannot go inside it. Pick its parent.'}
          </span>
          <span class="actions">
            <button class="mini" onClick=${onClose}>Cancel</button>
            <button class="go sm"
                    disabled=${!at.pickable}
                    onClick=${() => { onPick(at.path || '.'); onClose(); }}>Use this folder</button>
          </span>
        </div>
      </div>
    </div>`;
}

/* --------------------------------------------------------------------- section */
function Section({ s, set, remove, only }) {
  const col = (id, patch) =>
    set({ ...s, cols: s.cols.map(c => (c.id === id ? { ...c, ...patch } : c)) });
  return html`
    <div class="sec">
      <div class="hd">
        <div><label>Section key — SHOUTY, the rule uses it</label>
          <input type="text" placeholder="ROWS" value=${s.key}
                 onInput=${e => set({ ...s, key: e.target.value })}/></div>
        <div><label>Heading shown on the page</label>
          <input type="text" placeholder="Cases" value=${s.title}
                 onInput=${e => set({ ...s, title: e.target.value })}/></div>
        ${!only && html`<button class="x" title="remove section" onClick=${remove}>×</button>`}
      </div>
      <table>
        <thead><tr>
          <th class="c1">Column header</th><th class="c2">Width</th>
          <th class="c3">Align</th><th>Field the rule fills</th><th class="c4"></th>
        </tr></thead>
        <tbody>
          ${s.cols.map(c => html`
            <tr key=${c.id}>
              <td><input type="text" placeholder="Case Number" value=${c.header}
                         onInput=${e => col(c.id, { header: e.target.value })}/></td>
              <td><input type="text" value=${c.width}
                         onInput=${e => col(c.id, { width: e.target.value })}/></td>
              <td><select value=${c.align} onChange=${e => col(c.id, { align: e.target.value })}>
                    ${['Left', 'Right', 'Center'].map(a => html`<option key=${a}>${a}</option>`)}
                  </select></td>
              <td><input type="text" placeholder="caseNumber" value=${c.field}
                         onInput=${e => col(c.id, { field: e.target.value })}/></td>
              <td>${s.cols.length > 1 && html`<button class="x"
                    onClick=${() => set({ ...s, cols: s.cols.filter(x => x.id !== c.id) })}>×</button>`}</td>
            </tr>`)}
        </tbody>
      </table>
      <button class="mini" onClick=${() => set({ ...s, cols: [...s.cols, newCol()] })}>+ column</button>
    </div>`;
}

/* ------------------------------------------------------------------------- app */
function App() {
  const [boot, setBoot] = useState(null);
  const [project, setProject] = useState('');
  const [browsing, setBrowsing] = useState(false);
  const [tpl, setTpl] = useState('');
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [intent, setIntent] = useState('');
  const [sections, setSections] = useState([newSection()]);
  const [params, setParams] = useState([newParam()]);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [imported, setImported] = useState(null);
  const [secOpen, setSecOpen] = useState(false);
  const [impErr, setImpErr] = useState('');
  const [look, setLook] = useState(null);
  const [lookErr, setLookErr] = useState('');
  const [watching, setWatching] = useState(null);

  // A folder-view export answers the sections, the columns and the root entity outright -
  // they are the panels of a screen someone already designed. Retyping them by hand is
  // both slow and a chance to get a path wrong.
  const applyForm = f => {
    setSections(f.panels.map(p => ({
      id: uid(), key: p.key, title: p.label,
      cols: p.columns.map(c => ({
        id: uid(), header: c.header,
        width: Math.max(8, Math.round(100 / p.columns.length)),
        align: 'Left', field: c.field,
      })),
    })));
    // Follow the upload, but never clobber a name the user typed. "Untouched" means empty
    // or still exactly what the LAST import produced - so a second export replaces the
    // first one's name, while anything hand-edited survives.
    const derived = (f.formName || 'Report').replace(/[^A-Za-z0-9]+/g, '_');
    const prior = imported && !imported.choose ? imported : null;
    const priorName = prior ? (prior.formName || 'Report').replace(/[^A-Za-z0-9]+/g, '_') : '';
    if (!name || name === priorName) setName(derived);
    if (!title || (prior && title === prior.formName)) setTitle(f.formName || '');
    setImported(f);
    setSecOpen(true);
  };

  const onFile = e => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setImpErr(''); setImported(null);
    file.arrayBuffer().then(buf =>
      fetch('/api/formexport?name=' + encodeURIComponent(file.name),
            { method: 'POST', body: buf })
        .then(r => r.json())
        .then(d => {
          if (!d.ok) return setImpErr(d.message);
          if (d.forms.length === 1) return applyForm(d.forms[0]);
          setImported({ choose: d.forms });   // several views in one archive - let them pick
        }));
    e.target.value = '';
  };

  // The example layout. Uploaded now, but only COPIED into the report folder when the spec
  // is written - until then it is a temp file the server holds, like the folder-view export.
  const onLook = e => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setLookErr(''); setLook(null);
    file.arrayBuffer().then(buf =>
      fetch('/api/look?name=' + encodeURIComponent(file.name), { method: 'POST', body: buf })
        .then(r => r.json())
        .then(d => (d.ok ? setLook(d) : setLookErr(d.message))));
    e.target.value = '';
  };

  useEffect(() => {
    fetch('/api/bootstrap').then(r => r.json()).then(d => {
      setBoot(d);
      if (d.projects.length) setProject(d.projects[0].name);
    });
  }, []);

  // Is Claude parked on /api/wait? Shown live, because the answer decides what the Write
  // button DOES - hand the spec straight over, or print a command to copy - and a user who
  // only learns that from the result box learns it too late to restart anything.
  useEffect(() => {
    let alive = true;
    const tick = () => fetch('/api/watching').then(r => r.json())
      .then(d => alive && setWatching(d.watching)).catch(() => {});
    tick();
    const t = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!boot) return html`<div class="spin">Loading…</div>`;

  // A browsed folder may not be in the dropdown; show it as a real option rather than
  // silently falling back to the first project.
  const known = boot.projects.some(p => p.name === project);

  // Columns can come from a typed grid OR the brief OR a picture. `realCols` counts only the
  // columns that would actually survive submit() (header AND field filled), so the default
  // section's two blank rows do not read as "2 columns". `needsSay` is the client mirror of
  // the server rule: a template with nothing said about what goes on the page.
  const realCols = sections.reduce(
    (n, s) => n + s.cols.filter(c => c.header.trim() && c.field.trim()).length, 0);
  const hasBrief = intent.trim().length > 0;
  const needsSay = tpl && tpl !== PICTURE && realCols === 0 && !hasBrief;

  const submit = () => {
    setBusy(true); setRes(null);
    fetch('/api/spec', {
      method: 'POST',
      body: JSON.stringify({
        project, name: name.trim(), title: title.trim(), intent: intent.trim(),
        template: tpl === PICTURE ? '' : tpl,
        look: look ? look.token : '',
        meta: [], tiles: [], variants: ['full', 'none'],
        root: 'Case', id: '19',
        sections: sections.map(s => ({
          key: (s.key || 'ROWS').trim().toUpperCase(),
          title: s.title.trim(),
          cols: s.cols.filter(c => c.header.trim() && c.field.trim())
                      .map(c => [c.header.trim(), Number(c.width) || 20, c.align, c.field.trim()]),
        })).filter(s => s.cols.length),
        params: params.filter(p => p.name.trim()).map(p => [p.name.trim(), p.type]),
      }),
    }).then(r => r.json()).then(d => { setBusy(false); setRes(d); });
  };

  return html`
    <${React.Fragment}>
      <header>
        <h1>JTI Report Builder</h1>
        <div class="root">workspace ${boot.root} — ${boot.rootWhy}</div>
      </header>
      ${boot.version && boot.version.stale && html`
        <div class="banner">⚠︎ ${boot.version.message}</div>`}
      <main>
        <h2>Project</h2>
        <div class="row end">
          <select value=${project} onChange=${e => setProject(e.target.value)}>
            ${boot.projects.map(p => html`
              <option key=${p.name} value=${p.name}>
                ${p.label} — ${p.reports} report${p.reports === 1 ? '' : 's'},
                ${p.sdk ? ' field list (SDK) on file' : ' no field list (SDK)'}${p.environment ? ', ' + p.environment : ''}
              </option>`)}
            ${!known && html`<option value=${project}>${project}  (browsed)</option>`}
          </select>
          <button class="mini fix"
                  onClick=${() => setBrowsing(true)}>Browse…</button>
        </div>
        <div class="hint">Not listed? <b>Browse</b> to any folder on this Mac — including
          Downloads or Home. Anything outside the workspace still works; it just will not
          show up in this list next time.</div>

        <h2>Template</h2>
        <div class="cards">
          ${boot.templates.map(t => html`
            <button key=${t.module} class=${'card' + (tpl === t.module ? ' sel' : '')}
                    onClick=${() => setTpl(t.module)} title=${t.detail}>
              ${t.preview && html`<img src=${t.preview} alt=${t.title}/>`}
              <div class="t">${t.title}</div>
              <div class="d">${t.one_liner}</div>
            </button>`)}
          <button class=${'card' + (tpl === PICTURE ? ' sel' : '')}
                  onClick=${() => setTpl(PICTURE)}
                  title="Send a screenshot, a PDF, or a report from another system">
            ${look && look.kind !== 'application/pdf'
              ? html`<img src=${look.url} alt=${look.name}/>`
              : html`<div class="ph">${look ? '\u{1F4C4} ' + look.name : '\u2295'}</div>`}
            <div class="t">None of these — match a picture</div>
            <div class="d">Upload a screenshot, a PDF, or a report from another system.</div>
          </button>
        </div>
        ${tpl === PICTURE && html`
          <div class="pick">
            <div class="hint">Claude reads the picture, starts from whichever template is
              closest, and matches its columns, grouping and section order. Say in the brief
              below if you want the picture's colours and fonts too — otherwise the JTI
              masthead and styling stay. Charts and anything interactive cannot be
              reproduced: a report is paper.</div>
            <input type="file" accept="image/*,.pdf" onChange=${onLook}/>
            ${lookErr && html`<div class="out err">${lookErr}</div>`}
            ${look && html`<div class="out ok">Attached <b>${look.name}</b> —
              ${Math.max(1, Math.round(look.bytes / 1024))} KB. It gets copied into the
              report folder as <code>reference/${look.name}</code> so the build can look at
              it.</div>`}
          </div>`}

        <h2>Start from a folder view (optional)</h2>
        <div class="hint">Export a folder view from eSeries — <b>System Setup → Screens →
          Folder Views</b>, then Export — and drop the <code>FORM-*.zip</code> here. Its
          panels become sections and its columns become columns, with the real field paths
          already filled in.</div>
        <input type="file" accept=".zip,.xml" onChange=${onFile}/>
        ${impErr && html`<div class="out err">${impErr}</div>`}
        ${imported && imported.choose && html`
          <div class="out ok">
            <div>That archive holds ${imported.choose.length} folder views — which one?</div>
            <div class="actions" style=${undefined}>
              ${imported.choose.map(f => html`
                <button key=${f.code} class="mini" onClick=${() => applyForm(f)}>
                  ${f.formName} (${f.panels.length} panels)</button>`)}
            </div>
          </div>`}
        ${imported && !imported.choose && html`
          <div class="out ok">Loaded <b>${imported.formName}</b> — root entity
            <code>${imported.root}</code>, ${imported.panels.length} panels filled in below.
            Widths are evenly split; adjust them and drop any column you do not want.</div>`}

        <h2>Report</h2>
        <div class="row">
          <div><label>File name — letters, digits, underscores</label>
            <input type="text" placeholder="Cases_By_Type" value=${name}
                   onInput=${e => setName(e.target.value)}/></div>
          <div><label>Title on the page</label>
            <input type="text" placeholder="Cases By Type" value=${title}
                   onInput=${e => setTitle(e.target.value)}/></div>
        </div>
        <div class="mt12">
          <label>What should it show? Plain words — this is the brief, not a spec.</label>
          <textarea value=${intent} onInput=${e => setIntent(e.target.value)}
            placeholder="Every case filed in a date range, one row each, with its type and jurisdiction."></textarea>
          <div class="hint">If you leave the columns below blank, Claude builds them from this
            — so a clear sentence here can be the whole report. Fill the columns in only when
            you already know the exact fields you want.</div>
        </div>

        <button type="button" class="h2btn" onClick=${() => setSecOpen(o => !o)}>
          <h2>Sections and columns <span class="opt">\u2014 optional</span></h2>
          <span class="chev">${secOpen ? '\u2212' : '+'}</span>
          <span class="h2sum">${realCols > 0
            ? `${sections.length} section${sections.length === 1 ? '' : 's'}, ${realCols} column${realCols === 1 ? '' : 's'}${secOpen ? '' : ' \u2014 click to edit'}`
            : hasBrief
              ? 'none typed \u2014 Claude will build them from your brief'
              : 'none yet \u2014 type them here, or describe the report in the brief above'}</span>
        </button>
        ${secOpen && html`<${React.Fragment}>
          <div class="hint">One section per grid. Widths are relative — they get scaled to
            the page, so they need not add to 100.</div>
          ${sections.map(s => html`
            <${Section} key=${s.id} s=${s} only=${sections.length === 1}
              set=${u => setSections(xs => xs.map(x => (x.id === s.id ? u : x)))}
              remove=${() => setSections(xs => xs.filter(x => x.id !== s.id))}/>`)}
          <button class="mini" onClick=${() => setSections(xs => [...xs, newSection()])}>
            + section</button>
        <//>`}

        <h2>Launch inputs</h2>
        <div class="hint">What the person running the report fills in. Leave empty for a
          report that takes none.</div>
        <table>
          <thead><tr><th class="p1">Name</th><th>Type</th><th class="c4"></th></tr></thead>
          <tbody>
            ${params.map(p => html`
              <tr key=${p.id}>
                <td><input type="text" placeholder="StartDate" value=${p.name}
                      onInput=${e => setParams(xs => xs.map(x => x.id === p.id ? { ...x, name: e.target.value } : x))}/></td>
                <td><select value=${p.type}
                      onChange=${e => setParams(xs => xs.map(x => x.id === p.id ? { ...x, type: e.target.value } : x))}>
                      ${TYPES.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}
                    </select></td>
                <td><button class="x" onClick=${() => setParams(xs => xs.filter(x => x.id !== p.id))}>×</button></td>
              </tr>`)}
          </tbody>
        </table>
        <button class="mini" onClick=${() => setParams(xs => [...xs, newParam()])}>+ input</button>

        <div class="foot2">
          <button class="go" disabled=${busy || !tpl || (tpl === PICTURE && !look) || needsSay}
                  onClick=${submit}>
            ${busy ? 'Writing…' : 'Write spec.json'}</button>
          <span class=${'watch' + (watching ? ' on' : '')}>
            ${watching === null ? ''
              : watching ? 'Claude is watching — clicking Write hands it straight over'
                         : 'Claude is not watching — you will get a command to paste'}</span>
          ${!tpl && html`<span class="hint ml12">Pick a template first.</span>`}
          ${tpl === PICTURE && !look && html`
            <span class="hint ml12">Attach the picture you want it to look like.</span>`}
          ${needsSay && html`<span class="hint ml12">Add columns, or describe the report in
            the brief above — one of the two.</span>`}
          ${res && html`
            <div class=${'out ' + (res.ok ? 'ok' : 'err')}>
              ${res.ok ? html`
                <${React.Fragment}>
                  <div>Wrote <code>${res.message}</code>.</div>
                  ${res.watched
                    ? html`<div class="note mt8"><b>Claude is watching and has picked this
                        up — go back to the chat.</b> Nothing to copy.</div>`
                    : html`<${React.Fragment}>
                        <div>Now run this in Claude Code:</div>
                        <pre>/jti-reports:build-report ${res.message}</pre>
                      <//>`}
                  <div class="note mt8">
                    Everything still goes through the gates — nothing here bypasses
                    verification.</div>
                <//>` : res.message}
            </div>`}
        </div>
      </main>
      ${browsing && html`<${FolderBrowser} onClose=${() => setBrowsing(false)}
                           onPick=${p => setProject(p)}/>`}
    <//>`;
}

ReactDOM.createRoot(document.getElementById('app')).render(html`<${App}/>`);
