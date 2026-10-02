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
const newCol = () => ({ id: uid(), header: '', width: 20, align: 'Left', field: '', link: false, sort: '',
                        aggregate: 'None', format: '', customFormat: '', truncate: '', open: true });
const newSection = () => ({ id: uid(), key: '', title: '', cols: [newCol(), newCol()] });
const newParam = () => ({ id: uid(), name: '', type: TYPES[0][0] });
// --jobs mode (/build-report) only: its session token on every upload. Empty in the default
// mode, so those requests are exactly what they always were.
const SESSION = { h: {} };
window.SESSION_HEADERS = () => SESSION.h;
const F = () => window.JTIFields;
const DRAFT = 'jti-builder-draft';
// A draft left by an EARLIER builder run (a tab closed without building, another day) is not
// put back into the form - a new /build-report starts clean. It waits here to be offered.
const OLD_DRAFT = 'jti-builder-draft-earlier';

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

/* ----------------------------------------------------------------------- drafts */
const draftCols = dr => (dr.sections || []).reduce((n, s) => n + (s.cols || []).filter(c => (c.field || '').trim()).length, 0);
const draftHasWork = dr => !!(dr.name || dr.title || (dr.intent || '').trim() || dr.tpl || draftCols(dr) || (dr.criteria || []).length);
const draftWhen = at => (at ? new Date(at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'an earlier session');
const draftSize = dr => {
  const c = draftCols(dr), k = (dr.criteria || []).length;
  const bits = [c && `${c} column${c === 1 ? '' : 's'}`, k && `${k} search criteri${k === 1 ? 'on' : 'a'}`].filter(Boolean);
  return bits.length ? ' (' + bits.join(', ') + ')' : '';
};

/* --------------------------------------------------------------------- launcher */
const NO_LAUNCHER = { on: false, icon: '', text: '', param: 'caseId', style: 'link' };
// The .vm puts the eSeries classes on the link (launcher.py BUTTON_CLASS) and eSeries draws
// the button. This preview only approximates those classes - it is not what ships.
const LAUNCH_STYLES = [['link', 'Text link'], ['blue', 'Blue button'], ['grey', 'Grey button'], ['red', 'Red button']];
const LAUNCH_CLASS = { blue: 'btn btn-primary', grey: 'btn btn-default', red: 'btn btn-danger' };
const LAUNCH_LOOK = {
  link: { color: '#054CFF' },
  blue: { background: '#337AB7', border: '1px solid #2E6DA4', color: '#fff' },
  grey: { background: '#fff', border: '1px solid #CCC', color: '#333' },
  red: { background: '#D9534F', border: '1px solid #D43F3A', color: '#fff' },
};
function launchCss(style, hasText) {
  if (style === 'link' || !LAUNCH_LOOK[style]) return LAUNCH_LOOK.link;
  return { display: 'inline-flex', alignItems: 'center', gap: '6px', padding: hasText ? '5px 12px' : '5px 8px',
           borderRadius: '4px', fontSize: '13px', fontWeight: 600, lineHeight: 1.2, whiteSpace: 'nowrap',
           textDecoration: 'none', cursor: 'pointer', verticalAlign: 'middle', ...LAUNCH_LOOK[style] };
}
const COMMON_ICONS = ['i-print', 'printer', 'i-report', 'i-document-pdf', 'i-pdf', 'i-open-in-new'];
function launcherIssue(l, cat) {
  const icon = (l.icon || '').trim();
  if (icon && cat && (cat.font.length || cat.svg.length) && !cat.font.includes(icon) && !cat.svg.includes(icon))
    return `"${icon}" is not an eSeries icon class - pick one from the list.`;
  if ((l.text || '').length > 80) return 'the link text is longer than 80 characters.';
  if (!/^[A-Za-z][A-Za-z0-9_]{0,59}$/.test((l.param || '').trim()))
    return 'name the launch input that receives the record id (letters, digits, underscores - e.g. caseId).';
  return '';
}
function LauncherStep({ n, value: l, set, icons, title }) {
  const cat = icons || { font: [], svg: [] };
  const upd = o => set(x => ({ ...x, ...o }));
  const icon = l.icon.trim();
  const fam = !icon ? '' : cat.font.includes(icon) ? 'font icon' : cat.svg.includes(icon) ? 'colour icon' : 'not an eSeries icon';
  return html`
    <section class=${'step' + (l.on ? ' done' : '')}>
      <div class="step-h"><div class="num">${l.on ? '✓' : n}</div>
        <div><h2>Launcher<span class="opt">optional</span></h2><p class="lead">A link or icon you
          paste into a folder view as static text (Velocity), so the report runs for the record on
          that screen with one click — no search form.</p></div></div>
      <label class="cb"><input type="checkbox" checked=${l.on} onChange=${e => upd({ on: e.target.checked })}/>
        I want static-text Velocity that runs this report</label>
      ${l.on && html`
        <div class="grid2 mt12">
          <div><label>Icon (optional)</label>
            <input type="text" list="jti-icons" placeholder="e.g. i-print" value=${l.icon}
                   onInput=${e => upd({ icon: e.target.value })}/>
            <datalist id="jti-icons">${[...cat.font, ...cat.svg].map(c => html`<option key=${c} value=${c}/>`)}</datalist>
            <div class="hint">${fam ? fam + ' · ' : ''}Quick picks: ${COMMON_ICONS.filter(c => cat.font.includes(c) || cat.svg.includes(c)).map((c, i) => html`${i ? ', ' : ''}<button key=${c} class="linkbtn" onClick=${() => upd({ icon: c })}>${c}</button>`)}.
              Every class is on the eSeries style guide, <b>/ecms/help/style</b>.</div></div>
          <div><label>Link text (optional)</label>
            <input type="text" maxLength="80" placeholder=${l.icon.trim() ? 'Icon only' : 'Run ' + (title || 'the report')} value=${l.text}
                   onInput=${e => upd({ text: e.target.value })}/>
            <div class="hint">Shown next to the icon. Blank with an icon: icon only.</div></div>
          <div><label>Look</label>
            <div class="seg">${LAUNCH_STYLES.map(([k, lbl]) => html`<button key=${k} type="button"
              class=${(l.style || 'link') === k ? 'on' : ''} onClick=${() => upd({ style: k })}>${lbl}</button>`)}</div>
            <div class="launch-preview">
              <a href="javascript:void(0)" style=${launchCss(l.style || 'link', !!(l.text.trim() || !icon))}
                 onClick=${e => e.preventDefault()}>${icon && html`<span class="lp-icon">${icon}</span>`}${(l.text.trim() || (icon ? '' : 'Run ' + (title || 'the report')))}</a>
            </div>
            <div class="hint">${LAUNCH_CLASS[l.style] ? html`Adds <code>class="${LAUNCH_CLASS[l.style]}"</code>; eSeries draws the button. ` : ''}Preview
              is approximate and shows the icon class by name; on the eSeries screen it is the real icon.</div></div>
          <div><label>Launch input that gets the record's id</label>
            <input type="text" value=${l.param} onInput=${e => upd({ param: e.target.value })}/>
            <div class="hint">The report is run with this input set to the id of the record on the
              screen. Added to the report if it is not one of the Search Criteria.</div></div>
        </div>`}
    </section>`;
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
  const [criteria, setCriteria] = useState([]);      // Search Criteria - optional
  // A static-text launcher for a folder view (spec.launcher) - generated by scaffold, never hand-written.
  const [launcher, setLauncher] = useState(NO_LAUNCHER);
  const [draftAt, setDraftAt] = useState(null);
  const [oldDraft, setOldDraft] = useState(null);  // a draft from an earlier run, offered not applied
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [imported, setImported] = useState(null);
  const [secOpen, setSecOpen] = useState(false);
  const [impErr, setImpErr] = useState('');
  const [look, setLook] = useState(null);
  const [lookErr, setLookErr] = useState('');
  const [watching, setWatching] = useState(null);
  // The "Done" button (--jobs mode): tells the /build-report worker to stop waiting, so the
  // Claude session ends its run instead of polling for a build that is never coming.
  const [stopping, setStopping] = useState(false);
  const [doneMsg, setDoneMsg] = useState(null);
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
      // The folder used last, if it still exists - otherwise the first listed project.
      const last = (d.recent || [])[0];
      if (last) setProject(last.name); else if (d.projects.length) setProject(d.projects[0].name);
      // A draft of this form - criteria and columns included - survives a reload. It lives in
      // this browser only; the submitted spec.json is the record.
      // Only a draft from THIS run (a reload) goes straight back in; an older one is offered.
      try {
        const dr = JSON.parse(localStorage.getItem(DRAFT) || 'null');
        if (dr && dr.v === 1 && dr.run && dr.run === d.run) {
          applyDraft(dr);
          setDraftAt(dr.at || null);
        } else if (dr && dr.v === 1 && draftHasWork(dr)) {
          localStorage.setItem(OLD_DRAFT, JSON.stringify(dr));
          localStorage.removeItem(DRAFT);
        } else localStorage.removeItem(DRAFT);
        const old = JSON.parse(localStorage.getItem(OLD_DRAFT) || 'null');
        if (old && old.v === 1) setOldDraft(old);
      } catch (e) { /* no storage: the form still works */ }
      if (d.jobs && window.JTIBuild) {
        SESSION.h = { 'X-JTI-Session': d.jobs.session };
        // A refresh comes back to its build - if the server still knows it. A job from an
        // earlier server's workspace (same address, different run) is forgotten, not
        // waited on forever.
        const j = window.JTIBuild.recall();
        if (j) fetch('/api/jobs/' + j.id + '?t=' + encodeURIComponent(j.token))
          .then(r => (r.ok ? r.json() : null))
          .then(d => {
            const st = d && d.job && d.job.status;
            if (!st) return window.JTIBuild.remember(null);
            if (j.linked || !window.JTIBuild.TERMINAL.includes(st)) return setJob({ id: j.id, token: j.token });
            window.JTIBuild.forget();          // finished and not asked for: start on a clean form
          })
          .catch(() => setJob({ id: j.id, token: j.token }));
      }
    });
  }, []);

  useEffect(() => {
    if (!boot) return;
    const t = setTimeout(() => {
      try { localStorage.setItem(DRAFT, JSON.stringify({ v: 1, run: boot.run, at: Date.now(), project, tpl, name, title, intent, sections, criteria, launcher })); }
      catch (e) { /* ignore */ }
    }, 300);
    return () => clearTimeout(t);
  }, [boot, project, tpl, name, title, intent, sections, criteria, launcher]);

  // Is Claude parked on /api/wait? Shown live, because the answer decides what the Write
  // button DOES - hand the spec straight over, or print a command to copy - and a user who
  // only learns that from the result box learns it too late to restart anything.
  useEffect(() => {
    let alive = true;
    // One id per page load. A poll already in flight when the tab closes can land AFTER the
    // close beacon; carrying the id lets the server ignore that straggler, while a reload
    // (a new id) still cancels the close.
    const page = Math.random().toString(36).slice(2);
    const tick = () => fetch('/api/watching?page=' + page).then(r => r.json())
      .then(d => { if (alive) { setWatching(d.watching); setStopping(!!d.stopping); } }).catch(() => {});
    tick();
    const t = setInterval(tick, 3000);
    // --jobs mode: closing (or reloading) the tab tells the server. A reload checks back in
    // at once and cancels it; a real close lets Claude stop without anyone returning to it.
    const bye = () => { const s = SESSION.h['X-JTI-Session'];
      if (s && navigator.sendBeacon) navigator.sendBeacon('/api/session/closed',
        new Blob([JSON.stringify({ session: s, page })], { type: 'application/json' })); };
    window.addEventListener('pagehide', bye);
    return () => { alive = false; clearInterval(t); window.removeEventListener('pagehide', bye); };
  }, []);

  if (!boot) return html`<div class="spin">Loading…</div>`;

  // A browsed folder may not be in the dropdown; show it as a real option rather than
  // silently falling back to the first project.
  // Workspace projects, then folders used before that this workspace does not list.
  const recentOnly = (boot.recent || []).filter(r => !r.listed);
  const allProjects = [...boot.projects, ...recentOnly];
  const known = allProjects.some(p => p.name === project);

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
        params: criteria.flatMap(c => F().paramsOf(c)),
        paths: Object.fromEntries(sections.flatMap(s => s.cols.filter(c => c.path && c.field.trim())
          .map(c => [c.field.trim(), c.path]))),
        // Every criterion is sent: a blank or clashing name blocks the build (critIssues)
        // rather than being dropped here without a word.
        criteria: criteria.map(c => ({
          path: c.path, label: c.name || F().human(c.field || 'input'), operator: c.operator, lookup: c.lookup,
          multi: c.multi, required: c.required, hidden: c.hidden, default: c.dflt,
          type: c.dtype, params: F().paramsOf(c).map(p => p[0]) })),
        launcher: launcher.on ? { icon: launcher.icon.trim(), text: launcher.text.trim(), param: launcher.param.trim(), style: launcher.style || 'link' } : undefined,
        columnOptions: Object.fromEntries(sections.flatMap(s => s.cols.filter(c => c.field.trim()).map(c =>
          [c.field.trim(), { link: !!c.link, sort: c.sort || '', aggregate: c.aggregate || 'None',
                             format: c.format || '', customFormat: c.customFormat || '', truncate: c.truncate || '' }]))),
      }),
    }).then(r => r.json()).then(d => {
      setBusy(false);
      if (jobsMode && d.ok) {
        const j = { id: d.job, token: d.token };
        // The job holds the submission now; a draft left behind would greet the next
        // session with a report that is already built.
        try { localStorage.removeItem(DRAFT); } catch (e) { /* ignore */ }
        setDraftAt(null);
        window.JTIBuild.remember(j); setJob(j); window.scrollTo(0, 0);
      } else setRes(d);
    });
  };
  const finish = () => {
    if (!confirm('Done for now?\n\nClaude stops waiting for builds and ends its /build-report run. '
                 + 'Your reports stay where they are. Run /build-report again to build more.')) return;
    fetch('/api/session/done', { method: 'POST', body: '{}',
                                 headers: { ...SESSION.h, 'Content-Type': 'application/json' } })
      .then(r => r.json()).then(d => { setDoneMsg(d.message || 'Claude is stopping.'); setStopping(!!d.stopping);
        window.JTIBuild.forget(); })          // the next session opens on a clean form
      .catch(() => setDoneMsg('Could not reach the builder - it may already be closed.'));
  };
  const another = () => { window.JTIBuild.remember(null); setJob(null); setRes(null); setName(''); };

  // ---- the two add panes: Search Criteria and Result Columns
  const colPaths = new Set(sections.flatMap(s => s.cols.filter(c => c.path).map(c => c.path)));
  const critPaths = new Set(criteria.filter(c => c.path).map(c => c.path));
  // A path already in the list is never added twice, however the add was triggered.
  const addCriteria = (items, opts) => setCriteria(xs => {
    const have = new Set(xs.map(c => c.path).filter(Boolean));
    // Two fields with one name (Case status, Person status) would be two launch inputs with
    // one name - bound to the same value. Prefix the parent instead: PersonStatus.
    const names = new Set(xs.map(c => c.name));
    const up = w => w.replace('[]', '').replace(/^./, ch => ch.toUpperCase());
    return [...xs, ...items.filter(({ pth }) => !have.has(pth)).map(({ f, pth }) => {
      const c = F().newCriterion(f, pth, opts);
      const segs = (pth || '').split('.').slice(1, -1);
      for (let i = segs.length - 1; names.has(c.name) && i >= 0; i--) c.name = up(segs[i]) + c.name;
      for (let k = 2; names.has(c.name); k++) c.name = c.name.replace(/\d*$/, '') + k;
      c.label = c.name; names.add(c.name);
      return c;
    })];
  });
  const addColumns = (items, opts) => setSections(xs => {
    const taken = new Set(xs.flatMap(s => s.cols.map(c => c.field)));
    const have = new Set(xs.flatMap(s => s.cols.map(c => c.path)).filter(Boolean));
    const cols = items.filter(({ pth }) => !have.has(pth)).map(({ f, pth }) => { const c = F().newColumn(f, pth, opts, taken); taken.add(c.field); return c; });
    const at = Math.max(0, xs.findIndex(s => String(s.id) === String(opts.into)));
    return xs.map((sec, i) => i !== at ? sec : { ...sec, key: sec.key || 'ROWS',
      cols: [...sec.cols.filter(c => c.header.trim() || c.field.trim() || c.path), ...cols] });
  });
  const sectionList = sections.map((sc, i) => ({ id: sc.id, label: sc.title || sc.key || 'Section ' + (i + 1) }));
  const startOver = () => { try { localStorage.removeItem(DRAFT); } catch (e) {} location.reload(); };
  function applyDraft(dr) {
    if (dr.project !== undefined) setProject(dr.project);
    setTpl(dr.tpl || ''); setName(dr.name || ''); setTitle(dr.title || ''); setIntent(dr.intent || '');
    if (Array.isArray(dr.sections) && dr.sections.length) setSections(dr.sections);
    if (Array.isArray(dr.criteria)) setCriteria(dr.criteria);
    setLauncher(dr.launcher && typeof dr.launcher === 'object' ? { ...NO_LAUNCHER, ...dr.launcher } : NO_LAUNCHER);
  }
  const dropOld = () => { try { localStorage.removeItem(OLD_DRAFT); } catch (e) {} setOldDraft(null); };
  const restoreOld = () => { applyDraft(oldDraft); setDraftAt(oldDraft.at || null); dropOld(); };

  const tplObj = boot.templates.find(t => t.module === tpl);
  const projObj = allProjects.find(p => p.name === project);
  const tplDone = !!tpl && (tpl !== PICTURE || !!look);
  const contentDone = realCols > 0 || hasBrief || (tpl === PICTURE && !!look);
  const namedInputs = criteria.flatMap(c => F().paramsOf(c).map(p => p[0]));
  const critIssues = F().problems(criteria).filter(b => !b.warn);
  const launchIssue = launcher.on ? launcherIssue(launcher, boot.icons) : '';
  const canBuild = !(busy || !tpl || (tpl === PICTURE && !look) || needsSay || critIssues.length || launchIssue);
  const Num = ({ n, done }) => html`<div class="num">${done ? '✓' : n}</div>`;

  if (jobsMode && job) return html`
    <${React.Fragment}>
      <${AppBar} boot=${boot} watching=${watching} jobsMode=${jobsMode} stopping=${stopping} onDone=${finish}/>
      <${DoneBar} msg=${doneMsg} watching=${watching}/>
      <main class="shell one">
        <${window.JTIBuild.BuildScreen} job=${job} stages=${boot.jobs.stages} onAnother=${another}/>
      </main>
      <${Foot} boot=${boot}/>
    <//>`;

  return html`
    <${React.Fragment}>
      <${AppBar} boot=${boot} watching=${watching} jobsMode=${jobsMode} stopping=${stopping} onDone=${finish}/>
      <${DoneBar} msg=${doneMsg} watching=${watching}/>
      ${boot.version && boot.version.stale && html`
        <div class="banner">⚠︎ ${boot.version.message}</div>`}
      ${oldDraft && !job && html`
        <div class="banner draft">An unsent report from ${draftWhen(oldDraft.at)} is saved in this
          browser: <b>${oldDraft.name || 'untitled'}</b>${draftSize(oldDraft)}.
          <button class="mini" onClick=${restoreOld}>Restore it</button>
          <button class="linkbtn" onClick=${dropOld}>Discard</button></div>`}
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
                    ${p.dd ? ' Data Dictionary on file' : p.sdk ? ' field list (SDK) on file' : ' no field list'}${p.environment ? ', ' + p.environment : ''}
                  </option>`)}
                ${recentOnly.length > 0 && html`<optgroup label="Recently used">
                  ${recentOnly.map(p => html`
                    <option key=${p.name} value=${p.name}>
                      ${p.label} (${p.where}) — ${p.reports} report${p.reports === 1 ? '' : 's'},
                      ${p.dd ? ' Data Dictionary on file' : p.sdk ? ' field list (SDK) on file' : ' no field list'}${p.environment ? ', ' + p.environment : ''}
                    </option>`)}</optgroup>`}
                ${!known && html`<option value=${project}>${project || 'Workspace folder'}  (browsed)</option>`}
              </select>
              <button class="mini fix" onClick=${() => setBrowsing(true)}>Browse…</button>
            </div>
            <div class="hint">Not listed? <b>Browse</b> to the folder. Every folder you build in is
              remembered and listed under <b>Recently used</b> next time, whichever folder
              Claude Code was started in.</div>
            ${projObj && !projObj.sdk && html`<div class="todo mt8"><b>No SDK on file for this
              project.</b> The build asks you to upload one and does not go on without it - it is
              how every field is checked. In eSeries: <b>System Setup → Metadata → Entities →
              Download SDK</b>.</div>`}
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
                  report folder as <code>verification/reference/${look.name}</code> so the build can look at
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

          <section class=${'step' + (criteria.length ? ' done' : '')}>
            <div class="step-h"><${Num} n="5" done=${criteria.length > 0}/>
              <div><h2>Search Criteria<span class="opt">optional</span></h2><p class="lead">What the person
                running the report fills in to narrow it down — its launch inputs. Pick the fields; set each
                one's operator, default and behaviour in the list below.</p></div></div>
            <${F().FieldBrowser} project=${project} purpose="criteria" taken=${critPaths} sections=${sectionList}
                                  onAdd=${addCriteria}/>
            <div class="listhead"><h3>Search Criteria Fields</h3><span>${criteria.length}</span>
              <button class="mini" onClick=${() => setCriteria(xs => [...xs, { ...F().newCriterion(null, '', {}), open: true }])}>+ Input by hand</button></div>
            <${F().CriteriaList} items=${criteria} setItems=${setCriteria}/>
          </section>

          <section class=${'step' + (realCols > 0 ? ' done' : '')}>
            <div class="step-h"><${Num} n="6" done=${realCols > 0}/>
              <div><h2>Result Columns<span class="opt">optional</span></h2><p class="lead">What each row of the
                report shows. Pick the fields; label, order, sort, format and group them in the list below.
                ${realCols === 0 && hasBrief ? ' None picked — Claude will build them from your brief.' : ''}</p></div></div>
            <${F().FieldBrowser} project=${project} purpose="results" taken=${colPaths} sections=${sectionList}
                                  onAdd=${addColumns}/>
            <div class="listhead"><h3>Result Columns</h3><span>${realCols}</span>
              <button class="mini" onClick=${() => setSections(xs => xs.map((x, i) => i === xs.length - 1 ? { ...x, cols: [...x.cols, newCol()] } : x))}>+ Column by hand</button>
              <button class="mini" onClick=${() => setSections(xs => [...xs, { ...newSection(), cols: [] }])}>+ Section</button></div>
            <${F().ResultsList} sections=${sections} setSections=${setSections}/>
          </section>

          <${LauncherStep} n="7" value=${launcher} set=${setLauncher} icons=${boot.icons} title=${title || name}/>
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
              <dt>Criteria</dt><dd class=${namedInputs.length ? '' : 'empty'}>${namedInputs.join(', ') || 'None'}</dd>
              <dt>Launcher</dt><dd class=${launcher.on ? '' : 'empty'}>${launcher.on
                ? [(LAUNCH_STYLES.find(x => x[0] === (launcher.style || 'link')) || LAUNCH_STYLES[0])[1], launcher.icon.trim(), launcher.text.trim() ? '“' + launcher.text.trim() + '”' : ''].filter(Boolean).join(' · ') : 'None'}</dd>
            </dl>
            <button class="go block" disabled=${!canBuild} onClick=${submit}>
              ${jobsMode ? (busy ? 'Starting…' : 'Build report')
                         : (busy ? 'Writing…' : 'Write spec.json')}</button>
            ${!tpl && html`<div class="todo">Pick a template first.</div>`}
            ${tpl === PICTURE && !look && html`<div class="todo">Attach the picture you want it to look like.</div>`}
            ${needsSay && html`<div class="todo">Add columns, or describe the report in the brief — one of the two.</div>`}
            ${launchIssue && html`<div class="todo">Launcher: ${launchIssue}</div>`}
            ${critIssues.length > 0 && html`<div class="todo">Fix ${critIssues.length === 1 ? 'a search criterion' : critIssues.length + ' search criteria'} first — ${critIssues[0].msg}</div>`}
            ${watching !== null && html`<div class=${'watch' + (watching ? ' on' : '')}><span class="dot"/>
              <span>${jobsMode ? (watching ? 'Claude is ready — the build starts as soon as you click.'
                                           : 'Claude is not waiting yet — the build starts when /build-report picks it up.')
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
                      : html`<div class="note mt8">This stand-alone form only writes the spec.
                          To build a report with progress, preview and downloads, run
                          <b>/build-report</b> in Claude Code - it opens the full builder.</div>`}
                  <//>` : res.message}
              </div>`}
            ${draftAt && html`<div class="note mt8">Draft kept in this browser · <button class="linkbtn" onClick=${startOver}>Start over</button></div>`}
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
function DoneBar({ msg, watching }) {
  if (!msg) return null;
  const gone = watching === false;
  return html`<div class=${'donebar' + (gone ? ' gone' : '')} role="status"><div class="in">
    <b>${gone ? 'Claude has stopped.' : msg}</b>
    <span>${gone ? 'The /build-report run in Claude Code has ended. Your reports are saved where each build said. '
                   + 'To build more, run /build-report again. You can close this tab.'
                 : 'This page will say when it has stopped.'}</span></div></div>`;
}

function AppBar({ boot, watching, jobsMode, stopping, onDone }) {
  return html`<header class="appbar"><div class="in">
    <div class="brand">
      <img src="/brand/journal-j.png" alt="" onError=${hideImg}/>
      <span class="sep"/>
      <div>
        <div class="ttl">Report Builder</div>
        <div class="sub">Journal Technologies · eSeries reports</div>
      </div>
    </div>
    <span class="grow"/>
    <span class="chip" title=${boot.root + ' — ' + boot.rootWhy}>
      <span class="ico">\u{1F4C1}</span>${boot.root}</span>
    ${watching !== null && html`<span class=${'status' + (watching ? ' on' : '')}>
      <span class="dot"/>${stopping && watching ? 'Claude stopping…' : watching ? 'Claude ready' : 'Claude not connected'}</span>`}
    ${jobsMode && watching && !stopping && html`<button class="mini done" onClick=${onDone}
        title="Finished? Tell Claude to stop waiting and end its /build-report run.">Done — stop Claude</button>`}
  </div></header>`;
}

function Foot({ boot }) {
  return html`<footer class="foot"><img src="/brand/journal-j.png" alt="" onError=${hideImg}/>
    Journal Technologies · JTI Report Builder${boot.version && boot.version.mine
      ? ' ' + boot.version.mine : ''}</footer>`;
}

ReactDOM.createRoot(document.getElementById('app')).render(html`<${App}/>`);
