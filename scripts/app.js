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
// --jobs mode (/test-report) only: its session token on every upload. Empty in the default
// mode, so those requests are exactly what they always were.
const SESSION = { h: {} };

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
                         onInput=${e => col(c.id, { field: e.target.value })}/>
                  ${c.path && html`<div class="fp-code" title="from the field browser">${c.path}</div>`}</td>
              <td>${s.cols.length > 1 && html`<button class="x"
                    onClick=${() => set({ ...s, cols: s.cols.filter(x => x.id !== c.id) })}>×</button>`}</td>
            </tr>`)}
        </tbody>
      </table>
      <button class="mini" onClick=${() => set({ ...s, cols: [...s.cols, newCol()] })}>+ column</button>
    </div>`;
}

/* ---------------------------------------------------------------- field browser */
// Click through the fields the project's SDK really has: start at the root entity, drill into
// related records and lists, and add a field as a column (mode "column") or as a launch input
// that filters on it (mode "criteria"). Paths are exactly what the build resolves later.
const human = n => n.replace(/^cf_/, '').replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  .replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());

function FieldPicker({ project, mode, added, onAdd }) {
  const [root, setRoot] = useState('Case');
  const [stack, setStack] = useState([]);          // [{seg, list, entity}] below the root
  const [data, setData] = useState(null);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const here = stack.length ? stack[stack.length - 1].entity : root;
  useEffect(() => { setStack([]); }, [project, root]);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    fetch('/api/fields?project=' + encodeURIComponent(project) + '&entity=' + encodeURIComponent(here))
      .then(r => r.json()).then(d => { if (alive) { setData(d); setBusy(false); setQ(''); } })
      .catch(() => alive && (setData({ ok: false, message: 'Could not reach the builder.' }), setBusy(false)));
    return () => { alive = false; };
  }, [project, here]);
  const pathOf = f => [root, ...stack.map(x => x.seg + (x.list ? '[]' : '')), f.name].join('.');
  if (data && !data.ok) return html`<div class="fp"><div class="fp-empty">${data.message}</div></div>`;
  const all = (data && data.fields) || [];
  const ql = q.trim().toLowerCase();
  const shown = all.filter(f => !ql || f.name.toLowerCase().includes(ql) || human(f.name).toLowerCase().includes(ql));
  const used = !ql && shown.filter(f => f.used > 0 && f.kind === 'value').sort((a, b) => b.used - a.used).slice(0, 8);
  const Row = ({ f }) => {
    const pth = pathOf(f);
    if (f.kind === 'opaque') return html`<div class="fp-row dim">
        <span class="fp-name">${human(f.name)}<span class="fp-code">${f.name}</span></span>
        <span class="fp-type" title="the SDK does not say what this list holds">list, contents unknown</span></div>`;
    if (f.kind !== 'value') return html`
      <button class="fp-row nav" onClick=${() => setStack(s => [...s, { seg: f.name, list: f.kind === 'collection', entity: f.target }])}>
        <span class="fp-name">${human(f.name)}<span class="fp-code">${f.name}</span></span>
        <span class="fp-type">${f.kind === 'collection' ? 'list of ' + f.targetShort : f.targetShort}</span>
        <span class="fp-go">›</span></button>`;
    const on = added.has(pth);
    return html`<div class="fp-row">
      <span class="fp-name">${human(f.name)}<span class="fp-code">${f.name}</span>
        ${f.used > 0 && html`<span class="fp-used" title=${'A property with this name is read by ' + f.used + ' rule(s) in this workspace - on any kind of record, so it is a hint, not proof.'}>in your rules</span>`}
        ${f.display && html`<span class="fp-used warnish" title="a display field eSeries builds for the screen; it may carry HTML">display</span>`}</span>
      <span class="fp-type">${f.label}</span>
      <button class=${'mini' + (on ? ' on' : '')} disabled=${on} onClick=${() => onAdd(f, pth)}>
        ${on ? '✓ Added' : mode === 'column' ? '+ Column' : '+ Filter'}</button></div>`;
  };
  return html`<div class="fp">
    <div class="fp-bar">
      ${data && data.roots && html`<select class="fp-root" value=${root} onChange=${e => setRoot(e.target.value)}>
        ${data.roots.map(r => html`<option key=${r} value=${r}>${r}</option>`)}</select>`}
      <div class="fp-crumbs">
        <button class="fp-crumb" onClick=${() => setStack([])}>${root}</button>
        ${stack.map((x, i) => html`<${React.Fragment} key=${i}><span class="fp-sep">›</span>
          <button class="fp-crumb" onClick=${() => setStack(s => s.slice(0, i + 1))}>${human(x.seg)}${x.list ? ' (each)' : ''}</button><//>`)}
      </div>
      <input type="text" class="fp-q" placeholder="Search fields" value=${q} onInput=${e => setQ(e.target.value)}/>
    </div>
    ${busy ? html`<div class="fp-empty"><span class="spin1"/> Reading ${here} from the SDK…</div>` : html`
      <div class="fp-list">
        ${used && used.length > 0 && html`<div class="fp-group">Names your rules already read</div>
          ${used.map(f => html`<${Row} key=${'u' + f.name} f=${f}/>`)}
          <div class="fp-group">All fields on ${data.entity}</div>`}
        ${shown.map(f => html`<${Row} key=${f.name} f=${f}/>`)}
        ${shown.length === 0 && html`<div class="fp-empty">No field on ${here} matches "${q}".</div>`}
      </div>
      <div class="fp-foot">From ${data ? data.sdk : 'the SDK'} · ${all.length} fields on ${data && data.entity}.
        Lists (“each”) give one value per related record.</div>`}
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
  const [params, setParams] = useState([]);          // optional: none until someone adds one
  const [pickCols, setPickCols] = useState(false);
  const [pickCrit, setPickCrit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [imported, setImported] = useState(null);
  const [secOpen, setSecOpen] = useState(false);
  const [impErr, setImpErr] = useState('');
  const [look, setLook] = useState(null);
  const [lookErr, setLookErr] = useState('');
  const [watching, setWatching] = useState(null);
  const [job, setJob] = useState(null);           // --jobs mode: the build being followed

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
            { method: 'POST', body: buf, headers: SESSION.h })
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
      fetch('/api/look?name=' + encodeURIComponent(file.name),
            { method: 'POST', body: buf, headers: SESSION.h })
        .then(r => r.json())
        .then(d => (d.ok ? setLook(d) : setLookErr(d.message))));
    e.target.value = '';
  };

  useEffect(() => {
    fetch('/api/bootstrap').then(r => r.json()).then(d => {
      setBoot(d);
      if (d.projects.length) setProject(d.projects[0].name);
      if (d.jobs && window.JTIBuild) {
        SESSION.h = { 'X-JTI-Session': d.jobs.session };
        // A refresh comes back to its build - if the server still knows it. A job from an
        // earlier server's workspace (same address, different run) is forgotten, not
        // waited on forever.
        const j = window.JTIBuild.recall();
        if (j) fetch('/api/jobs/' + j.id + '?t=' + encodeURIComponent(j.token))
          .then(r => (r.ok ? setJob(j) : window.JTIBuild.remember(null)))
          .catch(() => setJob(j));
      }
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

  const jobsMode = !!(boot.jobs && window.JTIBuild);
  const submit = () => {
    setBusy(true); setRes(null);
    fetch(jobsMode ? '/api/jobs' : '/api/spec', {
      method: 'POST',
      headers: jobsMode ? { 'Content-Type': 'application/json', ...SESSION.h } : undefined,
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
        paths: Object.fromEntries(sections.flatMap(s => s.cols.filter(c => c.path && c.field.trim())
          .map(c => [c.field.trim(), c.path]))),
        criteria: Object.values(params.filter(p => p.path && p.name.trim()).reduce((acc, p) => {
          (acc[p.group] = acc[p.group] || { path: p.path, kind: p.kind, params: [] }).params.push(p.name.trim());
          return acc; }, {})),
      }),
    }).then(r => r.json()).then(d => {
      setBusy(false);
      if (jobsMode && d.ok) {
        const j = { id: d.job, token: d.token };
        window.JTIBuild.remember(j); setJob(j); window.scrollTo(0, 0);
      } else setRes(d);
    });
  };
  const another = () => { window.JTIBuild.remember(null); setJob(null); setRes(null); setName(''); };

  // ---- field-browser picks: a column, or a launch input that filters on the field
  const colPaths = new Set(sections.flatMap(s => s.cols.filter(c => c.path).map(c => c.path)));
  const critPaths = new Set(params.filter(p => p.path).map(p => p.path));
  const addColumn = (f, pth) => {
    setSections(xs => {
      const taken = new Set(xs.flatMap(s => s.cols.map(c => c.field)));
      const segs = pth.split('.').slice(1).map(x => x.replace('[]', ''));
      let key = f.name.replace(/^cf_/, '');
      for (let i = segs.length - 2; taken.has(key) && i >= 0; i--)
        key = segs[i] + key[0].toUpperCase() + key.slice(1);
      const col = { id: uid(), header: human(f.name), width: 20, align: 'Left', field: key, path: pth };
      const [first, ...rest] = xs;
      const keep = first.cols.filter(c => c.header.trim() || c.field.trim());
      return [{ ...first, key: first.key || 'ROWS', cols: [...keep, col] }, ...rest];
    });
    setSecOpen(true);
  };
  const addCriteria = (f, pth) => {
    const base = human(f.name).replace(/\s+/g, '');
    const date = f.label === 'date', num = f.label === 'number';
    const group = uid();
    const rows = date
      ? [['From', 'java.util.Date'], ['To', 'java.util.Date']].map(([sfx, t]) =>
          ({ id: uid(), name: base + sfx, type: t, path: pth, kind: 'range', group }))
      : [{ id: uid(), name: base, type: num ? 'java.lang.Integer' : 'java.lang.String', path: pth,
           kind: num ? 'equals' : 'in', group }];
    setParams(xs => [...xs.filter(p => p.name.trim()), ...rows]);
  };

  const tplObj = boot.templates.find(t => t.module === tpl);
  const projObj = boot.projects.find(p => p.name === project);
  const tplDone = !!tpl && (tpl !== PICTURE || !!look);
  const contentDone = realCols > 0 || hasBrief || (tpl === PICTURE && !!look);
  const namedInputs = params.filter(p => p.name.trim()).map(p => p.name.trim());
  const canBuild = !(busy || !tpl || (tpl === PICTURE && !look) || needsSay);
  const Num = ({ n, done }) => html`<div class="num">${done ? '✓' : n}</div>`;

  if (jobsMode && job) return html`
    <${React.Fragment}>
      <${AppBar} boot=${boot} watching=${watching} jobsMode=${jobsMode}/>
      <main class="shell one">
        <${window.JTIBuild.BuildScreen} job=${job} stages=${boot.jobs.stages} onAnother=${another}/>
      </main>
      <${Foot} boot=${boot}/>
    <//>`;

  return html`
    <${React.Fragment}>
      <${AppBar} boot=${boot} watching=${watching} jobsMode=${jobsMode}/>
      ${boot.version && boot.version.stale && html`
        <div class="banner">⚠︎ ${boot.version.message}</div>`}
      <main class="shell">
        <div class="hero">
          <div class="copy">
            <div class="eyebrow">Journal Technologies · eSeries</div>
            <h1>Build a report</h1>
            <p>Choose where it goes and what it looks like, then say what it should show.
              Claude writes the rule and the layout, and every build runs through the same
              verification gates before you see it.</p>
            <ol class="how">
              <li><span>1</span>Pick a project and a template</li>
              <li><span>2</span>Describe it in plain words</li>
              <li><span>3</span>Get verified, ready-to-import files</li>
            </ol>
          </div>
          <img class="mark" src="/brand/journal-mark.png" alt="" onError=${hideImg}/>
        </div>

        <div class="form">
          <section class=${'step' + (projObj || project ? ' done' : '')}>
            <div class="step-h"><${Num} n="1" done=${!!(projObj || project)}/>
              <div><h2>Project</h2><p class="lead">The folder the report is built in.</p></div></div>
            <div class="row end">
              <select value=${project} onChange=${e => setProject(e.target.value)}>
                ${boot.projects.map(p => html`
                  <option key=${p.name} value=${p.name}>
                    ${p.label} — ${p.reports} report${p.reports === 1 ? '' : 's'},
                    ${p.sdk ? ' field list (SDK) on file' : ' no field list (SDK)'}${p.environment ? ', ' + p.environment : ''}
                  </option>`)}
                ${!known && html`<option value=${project}>${project || 'Workspace folder'}  (browsed)</option>`}
              </select>
              <button class="mini fix" onClick=${() => setBrowsing(true)}>Browse…</button>
            </div>
            <div class="hint">Not listed? <b>Browse</b> to any folder on this Mac — including
              Downloads or Home. Anything outside the workspace still works; it just will not
              show up in this list next time.</div>
          </section>

          <section class=${'step' + (tplDone ? ' done' : '')}>
            <div class="step-h"><${Num} n="2" done=${tplDone}/>
              <div><h2>Template</h2><p class="lead">The house layout to start from. Every one
                carries the JTI masthead and styling.</p></div></div>
            <div class="cards">
              ${boot.templates.map(t => html`
                <button key=${t.module} class=${'card' + (tpl === t.module ? ' sel' : '')}
                        onClick=${() => setTpl(t.module)} title=${t.detail}>
                  ${t.preview ? html`<img src=${t.preview} alt=${t.title}/>` : html`<div class="ph"/>`}
                  <div class="t">${t.title}</div>
                  <div class="d">${t.one_liner}</div>
                </button>`)}
              <button class=${'card' + (tpl === PICTURE ? ' sel' : '')}
                      onClick=${() => setTpl(PICTURE)}
                      title="Send a screenshot, a PDF, or a report from another system">
                ${look && look.kind !== 'application/pdf'
                  ? html`<img src=${look.url} alt=${look.name}/>`
                  : html`<div class="ph">${look ? '\u{1F4C4} ' + look.name : '⊕'}</div>`}
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
                <div class="mt12"><input type="file" accept="image/*,.pdf" onChange=${onLook}/></div>
                ${lookErr && html`<div class="out err">${lookErr}</div>`}
                ${look && html`<div class="out ok">Attached <b>${look.name}</b> —
                  ${Math.max(1, Math.round(look.bytes / 1024))} KB. It gets copied into the
                  report folder as <code>reference/${look.name}</code> so the build can look at
                  it.</div>`}
              </div>`}
          </section>

          <section class=${'step' + (imported && !imported.choose ? ' done' : '')}>
            <div class="step-h"><${Num} n="3" done=${!!(imported && !imported.choose)}/>
              <div><h2>Start from a folder view<span class="opt">optional</span></h2>
                <p class="lead">Export one from eSeries — <b>System Setup → Screens → Folder
                  Views</b>, then Export — and drop the <code>FORM-*.zip</code> here. Its panels
                  become sections and its columns become columns, with the real field paths
                  already filled in.</p></div></div>
            <input type="file" accept=".zip,.xml" onChange=${onFile}/>
            ${impErr && html`<div class="out err">${impErr}</div>`}
            ${imported && imported.choose && html`
              <div class="out ok">
                <div>That archive holds ${imported.choose.length} folder views — which one?</div>
                <div class="actions">
                  ${imported.choose.map(f => html`
                    <button key=${f.code} class="mini" onClick=${() => applyForm(f)}>
                      ${f.formName} (${f.panels.length} panels)</button>`)}
                </div>
              </div>`}
            ${imported && !imported.choose && html`
              <div class="out ok">Loaded <b>${imported.formName}</b> — root entity
                <code>${imported.root}</code>, ${imported.panels.length} panels filled in below.
                Widths are evenly split; adjust them and drop any column you do not want.</div>`}
          </section>

          <section class=${'step' + (name.trim() && contentDone ? ' done' : '')}>
            <div class="step-h"><${Num} n="4" done=${!!(name.trim() && contentDone)}/>
              <div><h2>Report</h2><p class="lead">Its name, its title, and in plain words what
                it should show.</p></div></div>
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
              <div class="hint">If you leave the columns blank, Claude builds them from this — so a
                clear sentence here can be the whole report. Fill the columns in only when you
                already know the exact fields you want.</div>
            </div>
          </section>

          <section class=${'step' + (secOpen ? ' open' : '') + (realCols > 0 ? ' done' : '')}>
            <button type="button" class="step-h" onClick=${() => setSecOpen(o => !o)}>
              <${Num} n="5" done=${realCols > 0}/>
              <div><h2>Sections and columns<span class="opt">optional</span></h2>
                <p class="lead h2sum">${realCols > 0
                  ? `${sections.length} section${sections.length === 1 ? '' : 's'}, ${realCols} column${realCols === 1 ? '' : 's'}${secOpen ? '' : ' — click to edit'}`
                  : hasBrief
                    ? 'None typed — Claude will build them from your brief'
                    : 'None yet — type them here, or describe the report in the brief above'}</p></div>
              <span class="right chev">${secOpen ? '−' : '+'}</span>
            </button>
            ${secOpen && html`<${React.Fragment}>
              <div class="pickbar">
                <button class=${'mini' + (pickCols ? ' on' : '')} onClick=${() => setPickCols(o => !o)}>
                  ${pickCols ? 'Hide fields' : 'Browse fields'}</button>
                <span class="hint">Click through the fields this project's eSeries really has, and
                  add them as columns — or type them below.</span>
              </div>
              ${pickCols && html`<${FieldPicker} project=${project} mode="column" added=${colPaths} onAdd=${addColumn}/>`}
              <div class="hint">One section per grid. Widths are relative — they get scaled to
                the page, so they need not add to 100.</div>
              ${sections.map(s => html`
                <${Section} key=${s.id} s=${s} only=${sections.length === 1}
                  set=${u => setSections(xs => xs.map(x => (x.id === s.id ? u : x)))}
                  remove=${() => setSections(xs => xs.filter(x => x.id !== s.id))}/>`)}
              <button class="mini" onClick=${() => setSections(xs => [...xs, newSection()])}>
                + section</button>
            <//>`}
          </section>

          <section class="step">
            <div class="step-h"><${Num} n="6" done=${namedInputs.length > 0}/>
              <div><h2>Launch inputs<span class="opt">optional</span></h2><p class="lead">What
                the person running the report fills in to narrow it down — a date range, a case
                type.</p></div></div>
            <div class="pickbar">
              <button class=${'mini' + (pickCrit ? ' on' : '')} onClick=${() => setPickCrit(o => !o)}>
                ${pickCrit ? 'Hide fields' : 'Browse fields'}</button>
              <span class="hint">Pick a field to filter on: a date becomes a From / To pair, anything
                else one input.</span>
            </div>
            ${pickCrit && html`<${FieldPicker} project=${project} mode="criteria" added=${critPaths} onAdd=${addCriteria}/>`}
            ${params.length === 0 ? html`<div class="empty-note">None yet. Leave it that way and
              Claude works out any inputs from your brief — asking only if it genuinely cannot
              tell — or add them here.</div>` : html`
            <table>
              <thead><tr><th class="p1">Name</th><th>Type</th><th></th><th class="c4"></th></tr></thead>
              <tbody>
                ${params.map(p => html`
                  <tr key=${p.id}>
                    <td><input type="text" placeholder="StartDate" value=${p.name}
                          onInput=${e => setParams(xs => xs.map(x => x.id === p.id ? { ...x, name: e.target.value } : x))}/></td>
                    <td><select value=${p.type}
                          onChange=${e => setParams(xs => xs.map(x => x.id === p.id ? { ...x, type: e.target.value } : x))}>
                          ${TYPES.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}
                        </select></td>
                    <td>${p.path && html`<span class="fp-code" title=${p.path}>filters ${p.path.split('.').slice(1).join(' › ')}</span>`}</td>
                    <td><button class="x" onClick=${() => setParams(xs => xs.filter(x => x.id !== p.id))}>×</button></td>
                  </tr>`)}
              </tbody>
            </table>`}
            <div class="actions"><button class="mini" onClick=${() => setParams(xs => [...xs, newParam()])}>+ input</button></div>
          </section>
        </div>

        <aside class="rail">
          <div class="summary"><div class="in">
            <h3>Your report</h3>
            ${(tplObj && tplObj.preview) || (look && look.kind !== 'application/pdf')
              ? html`<div class="thumb"><img src=${tplObj ? tplObj.preview : look.url} alt=""/></div>` : ''}
            <dl class="kv">
              <dt>Project</dt><dd class=${projObj || project ? '' : 'empty'}>${projObj ? projObj.label : (project || 'Workspace folder')}</dd>
              <dt>Template</dt><dd class=${tpl ? '' : 'empty'}>${tpl === PICTURE ? 'Match a picture' : tplObj ? tplObj.title : 'Not chosen'}</dd>
              <dt>File name</dt><dd class=${name.trim() ? '' : 'empty'}>${name.trim() || 'Not set'}</dd>
              <dt>Content</dt><dd class=${contentDone ? '' : 'empty'}>${realCols > 0
                ? `${realCols} column${realCols === 1 ? '' : 's'}`
                : hasBrief ? 'From your brief' : (tpl === PICTURE && look) ? 'From the picture' : 'Not described'}</dd>
              <dt>Inputs</dt><dd class=${namedInputs.length ? '' : 'empty'}>${namedInputs.join(', ') || 'None'}</dd>
            </dl>
            <button class="go block" disabled=${!canBuild} onClick=${submit}>
              ${jobsMode ? (busy ? 'Starting…' : 'Build report')
                         : (busy ? 'Writing…' : 'Write spec.json')}</button>
            ${!tpl && html`<div class="todo">Pick a template first.</div>`}
            ${tpl === PICTURE && !look && html`<div class="todo">Attach the picture you want it to look like.</div>`}
            ${needsSay && html`<div class="todo">Add columns, or describe the report in the brief — one of the two.</div>`}
            ${watching !== null && html`<div class=${'watch' + (watching ? ' on' : '')}><span class="dot"/>
              <span>${jobsMode ? (watching ? 'Claude is ready — the build starts as soon as you click.'
                                           : 'Claude is not waiting yet — the build starts when /test-report picks it up.')
                : watching ? 'Claude is watching — clicking Write hands it straight over.'
                           : 'Claude is not watching — you will get a command to paste.'}</span></div>`}
            ${jobsMode && boot.jobs.active && !job && html`<div class="out err">A build is already
              running (${boot.jobs.active.name}). One build at a time.</div>`}
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
                  <//>` : res.message}
              </div>`}
            <div class="assure">Nothing here bypasses verification — every build runs the same
              gates, and you look at every page before anything is imported.</div>
          </div></div>
        </aside>
      </main>
      <${Foot} boot=${boot}/>
      ${browsing && html`<${FolderBrowser} onClose=${() => setBrowsing(false)}
                           onPick=${p => setProject(p)}/>`}
    <//>`;
}

/* --------------------------------------------------------------------- chrome */
// A builder server started before the /brand route existed answers 404 for the logo while
// still serving this page from disk: hide the image rather than show a broken-image icon.
const hideImg = e => { e.target.style.display = 'none'; };
// The Journal Technologies mark, the product name, the workspace, and Claude's state -
// the same header on the form and on the build screen.
function AppBar({ boot, watching, jobsMode }) {
  return html`<header class="appbar"><div class="in">
    <div class="brand">
      <img src="/brand/journal-j.png" alt="" onError=${hideImg}/>
      <span class="sep"/>
      <div>
        <div class="ttl">Report Builder${jobsMode && html`<span class="tag">Test build</span>`}</div>
        <div class="sub">Journal Technologies · eSeries reports</div>
      </div>
    </div>
    <span class="grow"/>
    <span class="chip" title=${boot.root + ' — ' + boot.rootWhy}>
      <span class="ico">\u{1F4C1}</span>${boot.root}</span>
    ${watching !== null && html`<span class=${'status' + (watching ? ' on' : '')}>
      <span class="dot"/>${watching ? 'Claude ready' : 'Claude not connected'}</span>`}
  </div></header>`;
}

function Foot({ boot }) {
  return html`<footer class="foot"><img src="/brand/journal-j.png" alt="" onError=${hideImg}/>
    Journal Technologies · JTI Report Builder${boot.version && boot.version.mine
      ? ' ' + boot.version.mine : ''}</footer>`;
}

ReactDOM.createRoot(document.getElementById('app')).render(html`<${App}/>`);
