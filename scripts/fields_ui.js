/*
 * Field selection for the report builder, modelled on the eSeries form editor - not just
 * its look, its workflow (observed read-only on Eh Team Config, S-Case, 2026-09-30):
 *
 *   1. an ADD PANE that is always open: Start From, the entity path, Quick Find, one grouped
 *      multi-select list, Current Path, and the options that apply at add time;
 *   2. the LIST of what was added (Search Criteria Fields / Result Columns), in order;
 *   3. a per-item EDITOR for the rest - operator, pick-list behaviour, date range, default,
 *      required, hidden for a criterion; label, link, sort, aggregate, format, truncate,
 *      width and section for a result column.
 *
 * Every field, relation, type, pick-list and description comes from /api/fields (the
 * project's Data Dictionary, else its SDK). Options offered are the ones the real editor
 * offers; where a report cannot honour one the same way a search does, the item says so.
 *
 * Wrapped in an IIFE: app.js declares `html`, `uid`, `SESSION` at script scope, and a second
 * top-level `const html` would be a redeclaration error.
 */
(function () {
  const { useState, useEffect, useRef } = React;
  const html = htm.bind(React.createElement);
  const sess = () => (window.SESSION_HEADERS ? window.SESSION_HEADERS() : {});
  let n = 0; const nid = () => 'f' + (++n) + '_' + Date.now().toString(36);

  const human = s => s.replace(/^cf_/, '').replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
  const pascal = s => human(s).replace(/[^A-Za-z0-9]+/g, ' ').trim().split(' ')
    .map(w => w[0].toUpperCase() + w.slice(1)).join('');
  const dtypeOf = f => (f.lookup ? 'pick-list' : ({ date: 'date', number: 'number', decimal: 'decimal',
    'yes/no': 'yes/no' }[f.label] || 'text'));
  const JAVA = { date: 'java.util.Date', number: 'java.lang.Integer', decimal: 'java.lang.String',
                 'yes/no': 'java.lang.String', text: 'java.lang.String', 'pick-list': 'java.lang.String' };

  // Search Op values exactly as the eSeries criterion editor lists them; GREATER_THAN is in
  // the exports. "equals" is the report's reading of "-- No Condition --".
  const OPS = {
    text: [['EQUALS', 'equals'], ['STARTS_WITH', 'starts with'], ['ENDS_WITH', 'ends with'],
           ['CONTAINS', 'contains'], ['IN', 'in (a list)'], ['NOT_IN', 'not in'],
           ['BLANK', 'is blank'], ['NOT_BLANK', 'is not blank']],
    'pick-list': [['IN', 'is one of'], ['NOT_IN', 'is not one of'], ['BLANK', 'is blank'], ['NOT_BLANK', 'is not blank']],
    date: [['RANGE', 'in a date range (From / To)'], ['EQUALS', 'on a date'], ['BLANK', 'is blank'], ['NOT_BLANK', 'is not blank']],
    number: [['EQUALS', 'equals'], ['GREATER_THAN', 'greater than'], ['BLANK', 'is blank'], ['NOT_BLANK', 'is not blank']],
    decimal: [['EQUALS', 'equals'], ['GREATER_THAN', 'greater than'], ['BLANK', 'is blank'], ['NOT_BLANK', 'is not blank']],
    'yes/no': [['EQUALS', 'equals'], ['BLANK', 'is blank'], ['NOT_BLANK', 'is not blank']],
  };
  const NO_INPUT = op => op === 'BLANK' || op === 'NOT_BLANK';
  const AGG = [['None', 'None'], ['GROUP_BY', 'Group By'], ['COUNT', 'Count'], ['COUNT_DISTINCT', 'Count Distinct'],
               ['SUM', 'Sum'], ['MAX', 'Max'], ['MIN', 'Min'], ['AVG', 'Avg'], ['CONCAT', 'Concat']];
  const FORMATS = [['', 'As stored'], ['MM/dd/yyyy', 'Date - 09/30/2026'], ['MM/dd/yyyy h:mm a', 'Date and time'],
                   ['$#,##0.00', 'Currency - $1,234.50'], ['#,##0', 'Number - 1,234'], ['YES_NO', 'Yes / No'],
                   ['CUSTOM', 'Custom (@value)']];

  /** the input names a criterion becomes on the report's launch form */
  function paramsOf(c) {
    if (c.hidden || NO_INPUT(c.operator)) return [];
    if (c.dtype === 'date' && c.operator === 'RANGE') return [[c.name + 'From', JAVA.date], [c.name + 'To', JAVA.date]];
    return [[c.name, c.type || JAVA[c.dtype] || JAVA.text]];
  }

  function newCriterion(f, pth, opts) {
    const dt = f ? dtypeOf(f) : 'text';
    return { id: nid(), path: pth || '', field: f ? f.name : '', label: f ? human(f.name) : '',
             name: f ? pascal(f.name) : '', dtype: dt, lookup: f ? f.lookup || null : null,
             values: f && f.values ? f.values : [],
             operator: dt === 'date' ? 'RANGE' : dt === 'pick-list' ? 'IN' : 'EQUALS',
             multi: dt === 'pick-list', lookupFormat: 'CODE', required: !!(opts && opts.required),
             hidden: !!(opts && opts.hidden), dflt: (opts && opts.dflt) || '',
             type: JAVA[dt], manual: !f, open: false };
  }

  function newColumn(f, pth, opts, taken) {
    const segs = pth.split('.').slice(1).map(x => x.replace('[]', ''));
    let key = f.name.replace(/^cf_/, '');
    for (let i = segs.length - 2; taken.has(key) && i >= 0; i--) key = segs[i] + key[0].toUpperCase() + key.slice(1);
    const dt = dtypeOf(f);
    return { id: nid(), header: human(f.name), width: 20, align: dt === 'number' || dt === 'decimal' ? 'Right' : 'Left',
             field: key, path: pth, dtype: dt, lookup: f.lookup || null, link: !!(opts && opts.link),
             sort: '', aggregate: (opts && opts.aggregate) || 'None',
             format: dt === 'date' ? 'MM/dd/yyyy' : '', customFormat: '', truncate: '', open: false };
  }

  /* ------------------------------------------------------------------ the add pane */
  function FieldBrowser({ project, purpose, taken, sections, onAdd }) {
    const [root, setRoot] = useState('Case');
    const [stack, setStack] = useState([]);
    const [data, setData] = useState(null);
    const [q, setQ] = useState('');
    const [busy, setBusy] = useState(true);
    const [sel, setSel] = useState([]);
    const [focus, setFocus] = useState(null);
    const [upErr, setUpErr] = useState('');
    const [reload, setReload] = useState(0);
    // add-time options - the ones the eSeries add pane offers for this purpose
    const [required, setRequired] = useState(false);
    const [hidden, setHidden] = useState(false);
    const [dflt, setDflt] = useState('');
    const [link, setLink] = useState(false);
    const [aggregate, setAggregate] = useState('None');
    const [into, setInto] = useState('');
    const listRef = useRef(null);
    const qfRef = useRef(null);
    const refocus = useRef(false);      // a keyboard open/up moves focus to Quick Find once the level loads
    const here = stack.length ? stack[stack.length - 1].entity : root;

    useEffect(() => { setStack([]); }, [project, root]);
    useEffect(() => { setQ(''); }, [here]);          // a new level starts with its whole list
    useEffect(() => {
      let alive = true;
      setBusy(true);
      fetch('/api/fields?project=' + encodeURIComponent(project) + '&entity=' + encodeURIComponent(here))
        .then(r => r.json()).then(d => { if (alive) { setData(d); setBusy(false); setSel([]); setFocus(null);
          if (refocus.current) { refocus.current = false; setTimeout(() => qfRef.current && qfRef.current.focus(), 0); } } })
        .catch(() => alive && (setData({ ok: false, message: 'Could not reach the builder.' }), setBusy(false)));
      return () => { alive = false; };
    }, [project, here, reload]);
    useEffect(() => { setDflt(''); }, [focus && focus.name]);

    const pathOf = f => [root, ...stack.map(x => x.seg + (x.list ? '[]' : '')), f.name].join('.');
    const attach = e => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      setUpErr(''); setBusy(true);
      file.arrayBuffer().then(buf => fetch('/api/dd?project=' + encodeURIComponent(project) + '&name=' +
          encodeURIComponent(file.name), { method: 'POST', body: buf, headers: sess() }))
        .then(r => r.json()).then(d => { setBusy(false); d.ok ? setReload(x => x + 1) : setUpErr(d.message); })
        .catch(() => { setBusy(false); setUpErr('Could not reach the builder.'); });
      e.target.value = '';
    };
    if (data && !data.ok) return html`<div class="fb fb-none"><div class="fp-empty">${data.message}</div>
      ${data.reason === 'no-sdk' && html`<div class="fp-attach">
        <label>Attach the Data Dictionary for this project</label>
        <input type="file" accept=".xlsx" disabled=${busy} onChange=${attach}/>
        <div class="hint">In eSeries: <b>System Setup → Data Dictionary</b>, then export. It is saved
          in the project folder and used for every report built there.</div>
        ${upErr && html`<div class="out err">${upErr}</div>`}</div>`}</div>`;

    const all = (data && data.fields) || [];
    const ql = q.trim().toLowerCase();
    const shown = all.filter(f => !ql || f.name.toLowerCase().includes(ql) || human(f.name).toLowerCase().includes(ql)
                                  || (f.description || '').toLowerCase().includes(ql));
    const GROUPS = [['value', 'Plain Fields'], ['rel', 'Entity Fields'], ['opaque', 'Other lists']];
    const inGroup = (f, k) => (k === 'rel' ? (f.kind === 'entity' || f.kind === 'collection') : f.kind === k);
    const order = GROUPS.flatMap(([k]) => shown.filter(f => inGroup(f, k)));      // keyboard order
    const levels = [{ label: root }, ...stack.map(x => ({ label: human(x.seg) + (x.list ? ' (each)' : '') }))];
    const open = f => { setStack(s => [...s, { seg: f.name, list: f.kind === 'collection', entity: f.target }]); setQ(''); };
    const up = () => stack.length && setStack(s => s.slice(0, -1));
    const toggle = f => {
      setFocus(f);
      if (taken.has(pathOf(f))) return;
      setSel(s => (s.includes(f.name) ? s.filter(x => x !== f.name) : [...s, f.name]));
    };
    const chosen = all.filter(f => sel.includes(f.name));
    const single = chosen.length === 1 ? chosen[0] : (chosen.length === 0 && focus && focus.kind === 'value' ? focus : null);
    const doAdd = () => {
      const items = chosen.filter(f => !taken.has(pathOf(f))).map(f => ({ f, pth: pathOf(f) }));
      if (!items.length) return;
      onAdd(items, purpose === 'criteria' ? { required, hidden, dflt: chosen.length === 1 ? dflt : '' }
                                          : { link, aggregate, into });
      setSel([]); setDflt('');
    };
    const focusRow = i => {
      const rows = listRef.current ? listRef.current.querySelectorAll('tr[data-k]') : [];
      if (rows[i]) rows[i].focus();
    };
    const onKey = (e, f, i) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); focusRow(i + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); focusRow(Math.max(0, i - 1)); }
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { /* the pane's handler adds - once */ }
      else if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        if (f.kind === 'entity' || f.kind === 'collection') { refocus.current = true; open(f); } else if (f.kind === 'value') toggle(f);
      } else if (e.key === 'Backspace' || e.key === 'ArrowLeft') { e.preventDefault(); if (stack.length) { refocus.current = true; up(); } }
    };

    return html`<div class="fb" onKeyDown=${e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); doAdd(); } }}>
      <div class="fb-left">
        <div class="fs-tools">
          <label class="sr">Start From</label>
          <select class="fs-root" aria-label="Start from" value=${root} onChange=${e => setRoot(e.target.value)}>
            ${((data && data.roots) || [root]).map(r => html`<option key=${r} value=${r}>${r}</option>`)}</select>
          <select class="fs-path" aria-label="Entity path" value=${stack.length}
                  onChange=${e => setStack(s => s.slice(0, Number(e.target.value)))}>
            ${levels.map((l, i) => html`<option key=${i} value=${i}>${' '.repeat(i)}${i ? '› ' : ''}${l.label}</option>`)}
          </select>
          <div class="fs-find"><span class="ico">⌕</span>
            <input type="search" ref=${qfRef} aria-label="Quick Find" placeholder="Quick Find" value=${q}
                   onInput=${e => setQ(e.target.value)}
                   onKeyDown=${e => { if (e.key === 'ArrowDown') { e.preventDefault(); focusRow(0); } }}/></div>
        </div>
        <div class="fs-scroll" ref=${listRef}>
          ${busy ? html`<div class="fp-empty"><span class="spin1"/> Reading ${here}…</div>` : html`
          <table class="fs-table" role="listbox" aria-multiselectable="true" aria-label=${'Fields on ' + here}>
            <thead><tr><th class="ck"></th><th>Field</th><th class="ty">Type</th><th class="li">List</th><th>Description</th></tr></thead>
            <tbody>
              ${GROUPS.map(([k, title]) => {
                const g = shown.filter(f => inGroup(f, k));
                return g.length > 0 && html`<${React.Fragment} key=${k}>
                  <tr class="grp"><td colspan="5">${title}<span>${g.length}</span></td></tr>
                  ${g.map(f => {
                    const i = order.indexOf(f), pth = pathOf(f);
                    const rowProps = { 'data-k': f.name, tabIndex: 0, onKeyDown: e => onKey(e, f, i) };
                    if (k === 'rel') return html`<tr key=${f.name} ...${rowProps} class="nav" onClick=${() => open(f)}
                        role="option" aria-label=${'Open ' + human(f.name)}>
                      <td class="ck go">›</td>
                      <td><b>${human(f.name)}</b><div class="code">${f.name}${f.kind === 'collection' ? '[]' : ''}</div></td>
                      <td class="ty">${f.kind === 'collection' ? 'list of ' + f.targetShort : f.targetShort}</td><td class="li"></td>
                      <td class="de">${f.description}</td></tr>`;
                    if (k === 'opaque') return html`<tr key=${f.name} ...${rowProps} class="dim">
                      <td class="ck"></td><td><b>${human(f.name)}</b><div class="code">${f.name}</div></td>
                      <td class="ty">list</td><td class="li"></td><td class="de">The model does not say what this list holds.</td></tr>`;
                    const done = taken.has(pth), on = sel.includes(f.name);
                    return html`<tr key=${f.name} ...${rowProps} role="option" aria-selected=${on}
                        class=${(on ? 'on ' : '') + (done ? 'done ' : '') + (focus && focus.name === f.name ? 'focus' : '')}
                        onClick=${() => toggle(f)} onFocus=${() => setFocus(f)}>
                      <td class="ck">${done ? html`<span class="tick" title="Already added">✓</span>`
                                            : html`<input type="checkbox" tabIndex="-1" checked=${on} readOnly/>`}</td>
                      <td><b>${human(f.name)}</b><div class="code">${f.name}</div></td>
                      <td class="ty">${f.label}</td>
                      <td class="li">${f.lookup && html`<span class="fp-pick">${f.lookup}</span>`}</td>
                      <td class="de">${f.description}</td></tr>`;
                  })}<//>`;
              })}
              ${shown.length === 0 && html`<tr><td colspan="5"><div class="fp-empty">No field on ${here} matches “${q}”.</div></td></tr>`}
            </tbody>
          </table>`}
        </div>
        <div class="fp-foot">${data ? data.sdk : ''} · ${data && data.source === 'dd' ? 'Data Dictionary' : 'SDK'} ·
          ${all.length} fields on ${data && data.entity} · Space selects, Enter opens, ← goes up, ⌘/Ctrl+Enter adds</div>
      </div>

      <div class="fb-right">
        <div class="fs-cur"><span class="k">Current Path</span>
          <div class="crumbs">${levels.map((l, i) => html`<${React.Fragment} key=${i}>
            ${i > 0 && html`<span class="sep">›</span>`}
            <button class="fp-crumb" onClick=${() => setStack(s => s.slice(0, i))}>${l.label}</button><//>`)}</div></div>
        <div class="fs-detail">
          ${chosen.length > 1 ? html`<div class="nm">${chosen.length} fields selected</div>
              <div class="picked">${chosen.map(f => html`<span key=${f.name} class="chip2">${human(f.name)}</span>`)}</div>`
          : focus ? html`<div class="nm">${human(focus.name)}</div>
              <div class="code">${pathOf(focus)}</div>
              <div class="chips"><span class="chip2">${focus.label}</span>
                ${focus.lookup && html`<span class="chip2 pick">${focus.lookup}</span>`}
                ${(focus.flags || []).map(x => html`<span key=${x} class="chip2">${x}</span>`)}</div>
              ${focus.description && html`<p>${focus.description}</p>`}
              ${focus.values && focus.values.length > 0 && html`<div class="vals">
                <div class="k">Values (${focus.values.length})</div>
                <div class="vlist">${focus.values.slice(0, 16).map((v, i) => html`<span key=${i}>${v}</span>`)}
                  ${focus.values.length > 16 && html`<em>+${focus.values.length - 16} more</em>`}</div></div>`}`
          : html`<div class="empty">Select fields in the list — several at once if you like. Open an Entity
              Field to see the fields inside it.</div>`}
        </div>
        <div class="fs-opts">
          ${purpose === 'criteria' ? html`
            <div class="optrow">
              <label class="cb"><input type="checkbox" checked=${required} onChange=${e => setRequired(e.target.checked)}/> Required</label>
              <label class="cb" title="Always applied with its default; not shown on the launch form">
                <input type="checkbox" checked=${hidden} onChange=${e => setHidden(e.target.checked)}/> Hidden</label>
            </div>
            <label>Default value</label>
            ${single && single.lookup && single.values.length
              ? html`<select value=${dflt} onChange=${e => setDflt(e.target.value)}><option value="">(none)</option>
                  ${single.values.map((v, i) => html`<option key=${i} value=${v}>${v}</option>`)}</select>`
              : single && dtypeOf(single) === 'date'
                ? html`<div class="row"><input type="text" placeholder="MM/dd/yyyy" value=${dflt} onInput=${e => setDflt(e.target.value)}/>
                    <button class="mini fix" onClick=${() => setDflt('@TODAY')}>Use Today</button></div>`
                : html`<input type="text" disabled=${chosen.length > 1} placeholder=${chosen.length > 1 ? 'set per criterion after adding' : ''}
                         value=${dflt} onInput=${e => setDflt(e.target.value)}/>`}`
          : html`
            <div class="optrow"><label class="cb" title="The column links to the record (recorded for the build)">
              <input type="checkbox" checked=${link} onChange=${e => setLink(e.target.checked)}/> Link</label></div>
            <label>Aggregate Function</label>
            <select value=${aggregate} onChange=${e => setAggregate(e.target.value)}>
              ${AGG.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}</select>
            ${sections.length > 1 && html`<label class="mt8">Into</label>
              <select value=${into} onChange=${e => setInto(e.target.value)}>
                ${sections.map(s => html`<option key=${s.id} value=${s.id}>${s.label}</option>`)}</select>`}`}
          <button class="go block mt12" disabled=${chosen.length === 0} onClick=${doAdd}>
            ${chosen.length ? `Add ${chosen.length} Field${chosen.length === 1 ? '' : 's'}` : 'Add Field(s)'}</button>
        </div>
      </div>
    </div>`;
  }

  /* ------------------------------------------------------------ the criteria list */
  function CriteriaList({ items, setItems }) {
    const upd = (id, patch) => setItems(xs => xs.map(x => (x.id === id ? { ...x, ...patch } : x)));
    const move = (i, d) => setItems(xs => { const a = xs.slice(); const j = i + d; if (j < 0 || j >= a.length) return a;
      [a[i], a[j]] = [a[j], a[i]]; return a; });
    if (!items.length) return html`<div class="empty-note">No criteria yet. Add fields above — or leave it
      empty and Claude works out any launch inputs from your brief, asking only if it genuinely cannot tell.</div>`;
    return html`<ol class="items">${items.map((c, i) => {
      const ops = OPS[c.dtype] || OPS.text;
      const ps = paramsOf(c);
      return html`<li key=${c.id} class=${'item' + (c.open ? ' open' : '')}>
        <div class="ih">
          <span class="grip" aria-hidden="true">≡</span>
          <button class="ilabel" onClick=${() => upd(c.id, { open: !c.open })} aria-expanded=${c.open}>
            <b>${c.label || c.name || 'Untitled input'}</b>
            ${c.lookup && html`<span class="fp-pick">${c.lookup}</span>`}
            <span class="isum">${(ops.find(o => o[0] === c.operator) || ['', ''])[1]}${c.required ? ' · required' : ''}${c.hidden ? ' · hidden' : ''}${c.dflt ? ' · default ' + c.dflt : ''}</span>
          </button>
          <span class="ipar">${ps.length ? ps.map(p => p[0]).join(' / ') : 'no launch input'}</span>
          <button class="x" title="Move up" onClick=${() => move(i, -1)} disabled=${i === 0}>↑</button>
          <button class="x" title="Move down" onClick=${() => move(i, 1)} disabled=${i === items.length - 1}>↓</button>
          <button class="x" title="Remove" onClick=${() => setItems(xs => xs.filter(x => x.id !== c.id))}>×</button>
        </div>
        ${c.open && html`<div class="ied">
          <div class="grid2">
            <div><label>Custom Label</label><input type="text" value=${c.label} onInput=${e => upd(c.id, { label: e.target.value })}/></div>
            <div><label>Input name (the rule reads it)</label><input type="text" value=${c.name}
                   onInput=${e => upd(c.id, { name: e.target.value.replace(/[^A-Za-z0-9_]/g, '') })}/></div>
            <div><label>Search Op</label><select value=${c.operator} onChange=${e => upd(c.id, { operator: e.target.value })}>
              ${ops.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}</select></div>
            ${c.manual && html`<div><label>Type</label><select value=${c.dtype}
                onChange=${e => upd(c.id, { dtype: e.target.value, type: JAVA[e.target.value], operator: (OPS[e.target.value] || OPS.text)[0][0] })}>
                ${['text', 'date', 'number', 'yes/no'].map(t => html`<option key=${t} value=${t}>${t}</option>`)}</select></div>`}
            ${c.dtype === 'pick-list' && html`<div><label>Lookup Item Format</label>
              <select value=${c.lookupFormat} onChange=${e => upd(c.id, { lookupFormat: e.target.value })}>
                <option value="CODE">Code</option><option value="LABEL">Label</option><option value="CODE_AND_LABEL">Code And Label</option></select></div>`}
            <div><label>Default</label>
              ${c.dtype === 'pick-list' && c.values.length
                ? html`<select value=${c.dflt} onChange=${e => upd(c.id, { dflt: e.target.value })}><option value="">(none)</option>
                    ${c.values.map((v, k) => html`<option key=${k} value=${v}>${v}</option>`)}</select>`
                : c.dtype === 'date'
                  ? html`<div class="row"><select value=${['@TODAY', '@THIS_WEEK'].includes(c.dflt) ? c.dflt : (c.dflt ? 'x' : '')}
                        onChange=${e => upd(c.id, { dflt: e.target.value === 'x' ? '' : e.target.value })}>
                        <option value="">(none)</option><option value="@TODAY">Today</option><option value="@THIS_WEEK">This week</option></select></div>`
                  : html`<input type="text" value=${c.dflt} onInput=${e => upd(c.id, { dflt: e.target.value })}/>`}</div>
          </div>
          <div class="optrow">
            <label class="cb"><input type="checkbox" checked=${c.required} onChange=${e => upd(c.id, { required: e.target.checked })}/> Required</label>
            <label class="cb"><input type="checkbox" checked=${c.hidden} onChange=${e => upd(c.id, { hidden: e.target.checked })}/> Hidden (always applied)</label>
            ${c.dtype === 'pick-list' && html`<label class="cb"><input type="checkbox" checked=${c.multi}
                onChange=${e => upd(c.id, { multi: e.target.checked })}/> Multi-select lookup</label>`}
          </div>
          ${c.path ? html`<div class="note">Path <code>${c.path}</code></div>` : html`<div class="note">Typed by hand — Claude finds the field it filters from your brief.</div>`}
          ${c.hidden && !c.dflt && !NO_INPUT(c.operator) && html`<div class="todo">A hidden criterion needs a default value — it is applied without asking.</div>`}
        </div>`}
      </li>`;
    })}</ol>`;
  }

  /* ---------------------------------------------------------- the result columns */
  function ResultsList({ sections, setSections }) {
    const upd = (sid, id, patch) => setSections(xs => xs.map(s => (s.id !== sid ? s
      : { ...s, cols: s.cols.map(c => (c.id === id ? { ...c, ...patch } : c)) })));
    const move = (sid, i, d) => setSections(xs => xs.map(s => { if (s.id !== sid) return s;
      const a = s.cols.slice(); const j = i + d; if (j < 0 || j >= a.length) return s; [a[i], a[j]] = [a[j], a[i]]; return { ...s, cols: a }; }));
    // ids compared as strings: a <select> hands back "3" for section id 3, and a strict match
    // there removed the column from its section without adding it anywhere (found in testing).
    const toSection = (from, id, to) => setSections(xs => {
      const src = xs.find(s => String(s.id) === String(from));
      const col = src && src.cols.find(c => c.id === id);
      if (!col || !xs.some(s => String(s.id) === String(to)) || String(from) === String(to)) return xs;
      return xs.map(s => String(s.id) === String(from) ? { ...s, cols: s.cols.filter(c => c.id !== id) }
                       : String(s.id) === String(to) ? { ...s, cols: [...s.cols, col] } : s); });
    const real = s => s.cols.filter(c => c.header.trim() || c.field.trim() || c.path);
    return html`<div class="results">${sections.map((s, si) => html`<div key=${s.id} class="rsec">
      <div class="rsh">
        <input type="text" class="rst" aria-label="Section heading" placeholder=${'Section ' + (si + 1) + ' heading'} value=${s.title}
               onInput=${e => setSections(xs => xs.map(x => x.id === s.id ? { ...x, title: e.target.value } : x))}/>
        <input type="text" class="rsk" aria-label="Section key" placeholder="KEY" value=${s.key}
               onInput=${e => setSections(xs => xs.map(x => x.id === s.id ? { ...x, key: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '') } : x))}/>
        ${sections.length > 1 && html`<button class="x" title="Remove section" onClick=${() => setSections(xs => xs.filter(x => x.id !== s.id))}>×</button>`}
      </div>
      ${real(s).length === 0 ? html`<div class="empty-note">No columns in this section yet.</div>` : html`
      <ol class="items">${real(s).map((c, i) => html`<li key=${c.id} class=${'item' + (c.open ? ' open' : '')}>
        <div class="ih">
          <span class="grip" aria-hidden="true">≡</span>
          <button class="ilabel" onClick=${() => upd(s.id, c.id, { open: !c.open })} aria-expanded=${c.open}>
            <b>${c.header || c.field || 'Untitled column'}</b>
            <span class="isum">${[c.link && 'link', c.sort && (c.sort === 'ASCEND' ? 'sorted ↑' : 'sorted ↓'),
              c.aggregate !== 'None' && (AGG.find(a => a[0] === c.aggregate) || [])[1], c.format && (FORMATS.find(f => f[0] === c.format) || [])[1]]
              .filter(Boolean).join(' · ')}</span></button>
          <span class="ipar">${c.width}</span>
          <button class="x" title="Move up" onClick=${() => move(s.id, i, -1)} disabled=${i === 0}>↑</button>
          <button class="x" title="Move down" onClick=${() => move(s.id, i, 1)} disabled=${i === real(s).length - 1}>↓</button>
          <button class="x" title="Remove" onClick=${() => setSections(xs => xs.map(x => x.id === s.id ? { ...x, cols: x.cols.filter(y => y.id !== c.id) } : x))}>×</button>
        </div>
        ${c.open && html`<div class="ied"><div class="grid2">
          <div><label>Custom Label</label><input type="text" value=${c.header} onInput=${e => upd(s.id, c.id, { header: e.target.value })}/></div>
          <div><label>Field the rule fills</label><input type="text" value=${c.field}
                 onInput=${e => upd(s.id, c.id, { field: e.target.value.replace(/[^A-Za-z0-9_]/g, '') })}/></div>
          <div><label>Width (relative)</label><input type="text" value=${c.width} onInput=${e => upd(s.id, c.id, { width: e.target.value.replace(/[^0-9]/g, '') })}/></div>
          <div><label>Align</label><select value=${c.align} onChange=${e => upd(s.id, c.id, { align: e.target.value })}>
            ${['Left', 'Center', 'Right'].map(a => html`<option key=${a}>${a}</option>`)}</select></div>
          <div><label>Sort By</label><select value=${c.sort} onChange=${e => upd(s.id, c.id, { sort: e.target.value })}>
            <option value="">(none)</option><option value="ASCEND">Ascending</option><option value="DESCEND">Descending</option></select></div>
          <div><label>Aggregate Function</label><select value=${c.aggregate} onChange=${e => upd(s.id, c.id, { aggregate: e.target.value })}>
            ${AGG.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}</select></div>
          <div><label>Format</label><select value=${c.format} onChange=${e => upd(s.id, c.id, { format: e.target.value })}>
            ${FORMATS.map(([v, l]) => html`<option key=${v} value=${v}>${l}</option>`)}</select></div>
          <div><label>Truncate (characters)</label><input type="text" value=${c.truncate} placeholder="no limit"
                 onInput=${e => upd(s.id, c.id, { truncate: e.target.value.replace(/[^0-9]/g, '') })}/></div>
          ${c.format === 'CUSTOM' && html`<div class="span2"><label>Custom Format - @value is the value</label>
            <input type="text" value=${c.customFormat} placeholder="@value (active)" onInput=${e => upd(s.id, c.id, { customFormat: e.target.value })}/></div>`}
          ${sections.length > 1 && html`<div><label>Section</label><select value=${s.id} onChange=${e => toSection(s.id, c.id, e.target.value)}>
            ${sections.map((x, k) => html`<option key=${x.id} value=${x.id}>${x.title || x.key || 'Section ' + (k + 1)}</option>`)}</select></div>`}
        </div>
        <div class="optrow"><label class="cb"><input type="checkbox" checked=${c.link} onChange=${e => upd(s.id, c.id, { link: e.target.checked })}/>
          Show link — opens the record</label></div>
        ${c.path ? html`<div class="note">Path <code>${c.path}</code></div>` : html`<div class="note">Typed by hand.</div>`}
        </div>`}
      </li>`)}</ol>`}
    </div>`)}</div>`;
  }

  window.JTIFields = { FieldBrowser, CriteriaList, ResultsList, newCriterion, newColumn, paramsOf, human };
})();
