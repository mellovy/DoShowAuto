(() => {
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const main = $('#main'), PAGE = document.body.dataset.page;
const S = { me: null, calc: '' };

async function api(path, body) {
  const o = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch('/api/' + path, o);
  if (r.status === 401) { location = '/login'; throw new Error('signed out'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(m, err) { const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = m; document.body.append(t); setTimeout(() => t.remove(), err ? 6000 : 2500); }
const val = id => ($('#' + id) || {}).value || '';
const field = (label, id, v = '', attrs = '', extra = '', hint = '') => `<label class="f"><span class="hl">${label}${extra}</span><input id="${id}" value="${esc(v)}" ${attrs}>${hint ? `<small class="hint">${hint}</small>` : ''}</label>`;
const lk = (txt, id) => `<button class="link" data-act="${id}">${txt}</button>`;
const chips = (arr) => arr.map(([t, a]) => `<span class="chip" data-act="${a}">${t}</span>`).join('');
const panel = (title, body) => `<div class="pdet"><h4>${title}</h4><div class="in">${body}</div></div>`;

// Every redraw swaps all of main's content. Shadow the innerHTML setter on main so a
// redraw keeps the scroll position and the focused field/selection (no jump, no lost
// caret) — the entrance animation lives on the `enter` class, so it never replays here.
if (main) {
  const native = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  Object.defineProperty(main, 'innerHTML', {
    configurable: true,
    get: () => native.get.call(main),
    set(html) {
      const ae = document.activeElement, keep = ae && ae.id && main.contains(ae) ? ae.id : null;
      const ss = keep ? ae.selectionStart : null, se = keep ? ae.selectionEnd : null, sy = window.scrollY;
      native.set.call(main, html);
      if (keep) { const e = $('#' + keep); if (e) { try { e.focus({ preventScroll: true }); if (ss != null && e.setSelectionRange) e.setSelectionRange(ss, se); } catch (_) {} } }
      if (window.scrollY !== sy) window.scrollTo(0, sy);
    }
  });
}
// run a handler with its triggering control disabled so a slow request can't double-submit
async function busy(el, fn) {
  if (el && el.dataset.busy) return;
  if (el) { el.dataset.busy = '1'; el.classList.add('busy'); if ('disabled' in el) el.disabled = true; }
  try { return await fn(); }
  finally { if (el) { delete el.dataset.busy; el.classList.remove('busy'); if ('disabled' in el) el.disabled = false; } }
}

// ---- validation helpers ----------------------------------------------
const isIP = s => { s = String(s || '').trim(); return /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.test(s) && s.split('.').every(o => +o <= 255); };
const inRange = (v, a, b) => /^\d+$/.test(String(v).trim()) && +v >= a && +v <= b;
// dotted mask -> prefix length, accepting "/24" or "24" too; null if not a subnet mask
const maskPrefix = v => { v = String(v || '').trim(); if (!v) return null; if (/^\/?\d{1,2}$/.test(v)) { const p = +v.replace('/', ''); return p <= 32 ? p : null; } if (!isIP(v)) return null; const inv = (~ip2n(v)) >>> 0; return (inv & (inv + 1)) === 0 ? v.split('.').reduce((a, o) => a + (+o).toString(2).replace(/0/g, '').length, 0) : null; };
const prefixMask = p => p == null ? '' : n2ip(maskOf(p));
// show inline hint/error under any field; bad=true colours it red, otherwise neutral guidance
function setMsg(id, text, bad) {
  const input = $('#' + id); if (!input) return;
  const host = input.closest('label.f') || input.parentElement; if (!host) return;
  let m = host.querySelector('.msg'); if (!m) { m = document.createElement('small'); m.className = 'msg'; host.append(m); }
  m.textContent = text || ''; m.classList.toggle('bad', !!bad && !!text);
}
// replay the section entrance animation on navigation (not on every redraw); dropped
// once it has played so freshly-rendered children don't animate again on a redraw
let enterT;
function enter() { if (!main) return; main.classList.remove('enter'); void main.offsetWidth; main.classList.add('enter'); clearTimeout(enterT); enterT = setTimeout(() => main.classList.remove('enter'), 450); }

// ---- console ----------------------------------------------------------
const term = $('#term');
function out(t, c = '') { if (!term) return; const d = document.createElement('div'); if (c) d.className = c; d.textContent = t; term.append(d); term.scrollTop = term.scrollHeight; }
function prompt_(c) { out('user@ds-auto:~$ ' + c, 'g'); }
function cfgOut(res) { (res.commands || []).forEach(c => out('user@ds-auto:~/config$ ' + c, 'g')); if (res.output) out(res.output, 'm'); }
let defaultCmd = 'show running-config';
async function runCmd(c) {
  c = (c || $('#cmdin').value || defaultCmd).trim(); prompt_(c); $('#cmdin').value = '';
  try { out((await api('console', { command: c })).output); } catch (e) { out(e.message, 'r'); }
}
function confirmDeploy(label, commands, remove) {
  return new Promise(resolve => {
    const dev = S.me && S.me.device;
    const w = document.createElement('div'); w.className = 'modal';
    w.innerHTML = `<div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="m-title">
      <div class="modal-hd" id="m-title">Confirm Configuration ${remove ? 'Removal' : 'Deployment'}</div>
      <div class="modal-bd">
        <p class="modal-meta">Target: <b>${esc(dev ? dev.name : 'No device')}</b> &middot; Action: <b>${esc(label || 'Configuration')}</b></p>
        <p class="modal-note">Review the exact commands below. A backup of the running configuration is saved before ${remove ? 'removal' : 'deployment'}.</p>
        <pre class="modal-cmds mono">${(commands || []).map(c => esc(c)).join('\n')}</pre>
      </div>
      <div class="modal-ft">
        <button class="btn red" data-r="no">CANCEL</button>
        <button class="btn blue" data-r="yes">${remove ? 'CONFIRM &amp; REMOVE' : 'CONFIRM &amp; DEPLOY'}</button>
      </div></div>`;
    const close = ok => { document.removeEventListener('keydown', onKey); w.remove(); resolve(ok); }, onKey = e => { if (e.key === 'Escape') close(false); };
    w.onclick = e => { if (e.target === w) close(false); };
    w.querySelector('[data-r=no]').onclick = () => close(false);
    const yes = w.querySelector('[data-r=yes]'); yes.onclick = () => close(true);
    document.addEventListener('keydown', onKey);
    document.body.append(w); yes.focus();
  });
}
async function apply(payload, label) {
  const remove = payload && payload.action === 'remove';
  let preview;
  try { preview = await api('preview', payload); }
  catch (e) { out('ERROR: ' + e.message, 'r'); toast(e.message, true); return false; }
  if (!await confirmDeploy(label, preview.commands, remove)) { out('Deployment cancelled — no changes were sent.', 'r'); return false; }
  try {
    const r = await api('apply', { ...payload, confirm: true, preview_id: preview.preview_id }); cfgOut(r);
    if (r.ok) { toast((label || 'Configuration') + (remove ? '' : ' applied') + (r.backup_id ? ' — backup #' + r.backup_id + ' stored' : '')); return true; }
    toast(r.error, true); return false;
  } catch (e) { out('ERROR: ' + e.message, 'r'); toast(e.message, true); return false; }
}
if (term) {
  $('#run').onclick = () => busy($('#run'), runCmd); $('#cmdin').onkeydown = e => { if (e.key === 'Enter') busy($('#run'), runCmd); };
  $('#dock-min').onclick = () => $('#console').classList.toggle('min');
  $('#dock-x').onclick = () => { $('#console').hidden = true; document.body.style.paddingBottom = '40px'; };
  $$('.dock-tabs .tab').forEach(b => b.onclick = () => { $$('.dock-tabs .tab').forEach(x => x.classList.toggle('on', x === b)); $('#pane-cons').hidden = b.dataset.t !== 'cons'; $('#pane-calc').hidden = b.dataset.t !== 'calc'; });
  $$('.mbtn').forEach(b => b.onclick = () => busy(b, async () => {
    prompt_('maintenance: ' + b.textContent);
    try {
      const r = await api('maint', { action: b.dataset.m });
      if (r.config) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([r.config], { type: 'text/plain' })); a.download = r.filename; a.click(); out('Saved ' + r.filename, 'g'); }
      else { out(r.message, 'g'); toast('Done'); }
    } catch (e) { out(e.message, 'r'); toast(e.message, true); }
  }));
}

// ---- subnet calculator -----------------------------------------------
const ip2n = s => s.split('.').reduce((a, o) => a * 256 + (+o), 0), n2ip = n => [24, 16, 8, 0].map(b => Math.floor(n / 2 ** b) % 256).join('.');
const maskOf = p => p ? (0xFFFFFFFF << (32 - p)) >>> 0 : 0;
function calc(c) {
  const m = (c || '').trim().match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/);
  if (!m || m.slice(1, 5).some(x => +x > 255) || +m[5] > 32) return null;
  const p = +m[5], ip = ip2n(m.slice(1, 5).join('.')), mk = maskOf(p), net = (ip & mk) >>> 0, bc = (net | (~mk >>> 0)) >>> 0;
  const hosts = p >= 31 ? 2 ** (32 - p) : 2 ** (32 - p) - 2;
  return { net: n2ip(net), mask: n2ip(mk), wild: n2ip(~mk >>> 0), bc: n2ip(bc), first: n2ip(p >= 31 ? net : net + 1), last: n2ip(p >= 31 ? bc : bc - 1), hosts, p };
}
function initCalc() {
  const pane = $('#pane-calc'); if (!pane) return; $('#calc-tab').hidden = PAGE !== 'configure';
  pane.innerHTML = `<div style="max-width:420px"><label class="f">IP / PREFIX<input id="calc-in" placeholder="10.50.0.0/22" value="${esc(S.calc)}"></label><pre id="calc-out" class="mono" style="margin:6px 0"></pre></div>`;
  const go = () => { S.calc = val('calc-in'); const r = calc(S.calc); $('#calc-out').textContent = r ? `Network     ${r.net}/${r.p}\nMask        ${r.mask}\nWildcard    ${r.wild}\nBroadcast   ${r.bc}\nFirst host  ${r.first}\nLast host   ${r.last}\nHosts       ${r.hosts}` : 'Enter an address like 192.168.1.0/24'; };
  $('#calc-in').oninput = go; go();
}

// ---- shell: network select, nav, status --------------------------------
async function boot() {
  S.me = await api('me');
  const sel = $('#network'); sel.innerHTML = S.me.networks.map(n => `<option ${n === S.me.network ? 'selected' : ''}>${esc(n)}</option>`).join('') + '<option value="__new">+ New network...</option>';
  sel.onchange = async () => { let n = sel.value; if (n === '__new') { n = (window.prompt('New network name') || '').trim(); if (!n) { sel.value = S.me.network; return; } } await api('network', { name: n }); location.reload(); };
  $$('nav.tabs > a, nav.tabs .dd > a').forEach(a => a.classList.toggle('on', a.dataset.p === PAGE));
  const d = S.me.device; $('#st-dev').textContent = d ? d.name : 'none'; $('#st-state').textContent = d ? d.status : '-'; $('#st-state').style.color = d && d.status === 'Up' ? '#0a7a4b' : '#c62828';
  if ($('#live-title')) $('#live-title').textContent = 'LIVE CONSOLE' + (d ? ': ' + d.name : '');
  initCalc();
  // replay the entrance only once the first view has actually painted (configure handles its own)
  const r = ({ general: pageGeneral, configure: pageConfigure, devices: pageDevices, logs: pageLogs })[PAGE]();
  if (PAGE !== 'configure') Promise.resolve(r).then(enter);
}
const needDev = () => { if (!S.me.device) { main.innerHTML = '<div class="panel">No device connected. Open <a href="/">General</a> and use SSH Access to connect to a Cisco device.</div>'; return true; } };

// ---- General ----------------------------------------------------------
function pageGeneral() {
  const u = S.me.user, d = S.me.device;
  main.innerHTML = `<div class="panel"><h3>&#9786; Admin Profile</h3><div class="row2" style="grid-template-columns:1fr 1fr 1fr">${field('Admin Username', 'p-user', u.username)}${field('Email Address', 'p-mail', u.email, 'type="email"')}<label class="f"><span>Password</span><input id="p-pw" type="password" placeholder="leave blank to keep" autocomplete="new-password"></label></div><div style="text-align:right"><button class="btn blue" id="p-save">UPDATE PROFILE</button></div></div>
  <div class="row2"><div class="panel"><h3>&lt;&gt; Basic Configuration</h3>${field('Hostname', 'b-host', d ? d.name : '')}<label class="f">Banner Message<textarea id="b-ban" rows="3" placeholder="Unauthorized access is strictly prohibited."></textarea></label>
  <label class="cb"><input type="checkbox" id="b-es"> Enable Secret</label><label class="cb"><input type="checkbox" id="b-enc"> Password Encryption</label>${field('Secret Key', 'b-sec', '', 'type="password" autocomplete="new-password"')}<button class="btn wide" id="b-apply">APPLY BASIC CONFIGURATION</button></div>
  <div><div class="panel"><h3>&#9000; SSH Access</h3>${field('IP Address', 's-ip', d ? d.host : '', 'placeholder="10.128.0.1"')}${field('Auth Secret', 's-sec', '', 'type="password" autocomplete="off"')}<label class="f">Login Method<select id="s-m"><option>Local Database</option></select></label><button class="btn blue wide" id="s-go">&#9000; CONNECT</button>
  <h3 style="margin-top:14px">AI Model Processing</h3><label class="cb"><input type="radio" name="ai" value="local" ${S.me.ai_mode === 'local' ? 'checked' : ''}> Local (Ollama)</label><label class="cb"><input type="radio" name="ai" value="cloud" ${S.me.ai_mode === 'cloud' ? 'checked' : ''}> Cloud API</label></div></div></div>`;
  $('#p-save').onclick = () => busy($('#p-save'), async () => { try { await api('profile', { username: val('p-user'), email: val('p-mail'), password: val('p-pw') }); toast('Profile updated'); } catch (e) { toast(e.message, true); } });
  $('#b-apply').onclick = () => busy($('#b-apply'), async () => { if (await apply({ kind: 'basic', hostname: val('b-host'), banner: val('b-ban'), enable_secret: $('#b-es').checked, secret: val('b-sec'), encryption: $('#b-enc').checked }, 'Basic configuration')) { $('#b-sec').value = ''; } });
  $('#s-go').onclick = () => busy($('#s-go'), async () => { prompt_('ssh connect ' + val('s-ip')); try { const r = await api('connect', { ip: val('s-ip'), secret: val('s-sec') }); out('Connection established to ' + r.hostname, 'g'); location.reload(); } catch (e) { out(e.message, 'r'); toast(e.message, true); } });
  $$('input[name=ai]').forEach(r => r.onchange = () => busy(r, () => api('settings', { ai_mode: r.value }).then(() => toast('AI model: ' + r.value)).catch(e => toast(e.message, true))));
  defaultCmd = 'show running-config'; if (d) runCmd('show running-config');
}

// ---- Configure --------------------------------------------------------
const VIEWS = { interfaces: vInterfaces, dhcp: vDhcp, vlans: vVlans, routing: vRouting, etherchannel: vEtherchannel, portsec: vPortsec };
const DEFCMD = { interfaces: 'show interfaces status', dhcp: 'show ip dhcp pool', vlans: 'show vlan brief', routing: 'show ip route', etherchannel: 'show etherchannel summary', portsec: 'show port-security' };
function pageConfigure() { const go = () => { const v = (location.hash || '#interfaces').slice(1); if (needDev()) return; const f = VIEWS[v] || vInterfaces; defaultCmd = DEFCMD[v] || DEFCMD.interfaces; $$('#cfgmenu a').forEach(a => a.style.fontWeight = a.hash === '#' + v ? '700' : ''); f().then(enter).catch(e => { main.innerHTML = `<div class="panel err">${esc(e.message)}</div>`; }); runCmd(defaultCmd); }; window.onhashchange = go; go(); }
const net24 = () => S.ifs.map(i => i.ip).filter(Boolean);
const search = (id, rowsSel) => { const q = $('#' + id); q && (q.oninput = () => $$(rowsSel).forEach(r => r.hidden = !r.textContent.toLowerCase().includes(q.value.toLowerCase()))); };
const wire = (map) => $$('[data-act]').forEach(e => e.onclick = ev => { ev.stopPropagation(); return busy(e, () => (map[e.dataset.act] || (() => {}))(e)); });
const done = async (ok, redraw) => { if (ok) { await redraw(); runCmd(defaultCmd); } };

async function vInterfaces() {
  const [ifs, vl] = await Promise.all([api('inventory?kind=interfaces'), api('inventory?kind=vlans')]); S.ifs = ifs; let cur = ifs[0] && ifs[0].name;
  const draw = () => {
    const i = ifs.find(x => x.name === cur) || {};
    main.innerHTML = `<div class="split"><div class="panel"><div class="hl"><h3>&#9919; Interface Inventory</h3><span><input id="q" placeholder="Search interfaces..."> <button class="btn blue sm" data-act="refresh">REFRESH</button></span></div>
    <table><tr><th>INTERFACE<th>STATUS<th>ASSIGNMENT<th>DESCRIPTION<th>IP ADDRESS<th>VLAN<th></tr>${ifs.map(x => `<tr class="clk ${x.name === cur ? 'sel' : ''}" data-n="${esc(x.name)}"><td class="mono">${esc(x.short)}<td><span class="tog ${x.up ? 'on' : ''}" data-tog="${esc(x.name)}"></span> ${x.up ? 'UP' : 'DOWN'}<td>${x.assignment}<td><i>${esc(x.description || '--')}</i><td class="mono">${esc(x.ip || 'unassigned')}${x.mask ? '/' + (calcMask(x.mask)) : ''}<td>${esc(x.vlan || '1')}<td>&#9998;</tr>`).join('')}</table></div>
    ${panel('DETAILS: ' + esc(i.short || ''), `<div class="seg"><button data-act="static" class="${i.assignment !== 'DHCP' ? 'on' : ''}">STATIC</button><button data-act="dhcp" class="${i.assignment === 'DHCP' ? 'on' : ''}">DHCP</button></div><input type="hidden" id="f-as" value="${i.assignment === 'DHCP' ? 'dhcp' : 'static'}">
    ${field('IP Address', 'f-ip', i.ip, 'placeholder="10.128.0.1" inputmode="decimal"', lk('SUGGEST NEXT', 'sugip'))}${field('Subnet Mask', 'f-mask', i.mask, 'placeholder="255.255.255.0 or /24"', lk('PULL FROM INVENTORY', 'pullmask'), 'Dotted mask or /prefix — the two are interchangeable.')}${field('Description', 'f-desc', i.description, 'placeholder="Uplink to Core"', '')}<div>${chips([['STANDARD UPLINK', 'uplink'], ['HOST PORT', 'host']])}</div>
    <label class="f" id="f-vlanwrap">VLAN Assignment<div style="display:flex;gap:6px"><input id="f-vlan" list="vls" placeholder="Search VLAN ID..." value="${i.vlan && i.vlan !== 'Trunk' ? esc(i.vlan) : ''}"><select id="f-tr" style="width:130px"><option value="0">Access VLAN</option><option value="1" ${i.vlan === 'Trunk' ? 'selected' : ''}>Trunk Mode</option></select></div></label><datalist id="vls">${vl.map(v => `<option value="${v.id}">${esc(v.name)}</option>`).join('')}</datalist>
    <button class="btn wide" data-act="apply" style="background:#0a7a4b">&#9654; APPLY CONFIGURATION</button>${cur ? `<button class="btn red wide" data-act="reset">&#8635; RESET INTERFACE${i.short ? ': ' + esc(i.short) : ''}</button>` : ''}`)}</div>`;
    $$('tr[data-n]').forEach(r => r.onclick = e => { if (e.target.dataset.tog) return; cur = r.dataset.n; draw(); });
    $$('[data-tog]').forEach(t => t.onclick = () => busy(t, async () => { const x = ifs.find(y => y.name === t.dataset.tog); await done(await apply({ kind: 'interface', interface: x.name, enabled: !x.up }, x.short + (x.up ? ' shutdown' : ' enabled')), load); }));
    search('q', 'tr[data-n]');
    $('#f-ip').oninput = () => setMsg('f-ip', val('f-ip') && !isIP(val('f-ip')) ? 'Enter a valid IPv4 address, e.g. 10.128.0.1.' : '', true);
    $('#f-mask').oninput = () => setMsg('f-mask', val('f-mask') && maskPrefix(val('f-mask')) == null ? 'Enter a dotted mask (255.255.255.0) or a /prefix (/24).' : '', true);
    $('#f-mask').onblur = () => { const p = maskPrefix(val('f-mask')); if (p != null) $('#f-mask').value = prefixMask(p); };
    const trunk = () => { const t = val('f-tr') === '1', inp = $('#f-vlan'); if (t) { inp.dataset.keep = inp.value || ''; inp.value = ''; } else if (inp.dataset.keep) { inp.value = inp.dataset.keep; inp.dataset.keep = ''; } inp.disabled = t; $('#f-vlanwrap').style.opacity = t ? '.45' : '1'; setMsg('f-vlan', t ? 'Trunk carries the allowed VLANs; the access VLAN field is not used.' : '', false); };
    $('#f-tr').onchange = trunk; trunk();
    wire({ refresh: load, reset: async () => done(await apply({ kind: 'interface', iface: cur, action: 'remove' }, 'Reset interface ' + cur), load), static: () => { $('#f-as').value = 'static'; $$('.seg button').forEach(b => b.classList.toggle('on', b.dataset.act === 'static')); }, dhcp: () => { $('#f-as').value = 'dhcp'; $$('.seg button').forEach(b => b.classList.toggle('on', b.dataset.act === 'dhcp')); },
      sugip: () => { const used = net24(), base = (val('f-ip') || used[0] || '192.168.1.1').split('.').slice(0, 3).join('.'); let m = 0; used.filter(x => x.startsWith(base + '.')).forEach(x => m = Math.max(m, +x.split('.')[3])); $('#f-ip').value = base + '.' + Math.min(254, m + 1); },
      pullmask: () => { const f = ifs.find(x => x.mask); if (f) $('#f-mask').value = f.mask; }, uplink: () => { $('#f-desc').value = 'Uplink to Core'; $('#f-tr').value = '1'; }, host: () => { $('#f-desc').value = 'Host Port'; $('#f-tr').value = '0'; },
      apply: async () => { if (val('f-as') === 'static' && val('f-ip') && !isIP(val('f-ip'))) return toast('IP address must be a valid IPv4 address', true); if (val('f-mask') && maskPrefix(val('f-mask')) == null) return toast('Subnet mask must be dotted (255.255.255.0) or a /prefix', true); done(await apply({ kind: 'interface', interface: cur, assignment: val('f-as'), ip: val('f-ip'), mask: val('f-mask'), description: val('f-desc'), vlan: val('f-vlan'), trunk: val('f-tr') === '1' }, 'Interface ' + cur), load); } });
  };
  const load = async () => { const n = await api('inventory?kind=interfaces'); ifs.splice(0, ifs.length, ...n); S.ifs = ifs; draw(); }; draw();
}
const calcMask = m => m.split('.').reduce((a, o) => a + (+o).toString(2).replace(/0/g, '').length, 0);

async function vDhcp() {
  const pools = await api('inventory?kind=dhcp'); let cur = pools[0] || {};
  const draw = () => {
    main.innerHTML = `<div class="split"><div class="panel"><div class="hl"><h3>DHCP Pools Inventory</h3><button class="btn" data-act="new">+ CREATE NEW POOL</button></div>
    <table><tr><th>POOL NAME<th>NETWORK<th>USABLE RANGE<th>LEASES<th>STATUS</tr>${pools.map(p => `<tr class="clk ${p.name === cur.name ? 'sel' : ''}" data-n="${esc(p.name)}"><td class="mono">${esc(p.name)}<td class="mono">${p.network}/${p.prefix}<td class="mono">${esc(p.range)}<td>${p.leased} / ${p.total} active<div class="bar"><i class="${p.status !== 'Active' ? 'hot' : ''}" style="width:${p.total ? Math.min(100, p.leased / p.total * 100) : 0}%"></i></div><td><span class="badge ${p.status === 'Active' ? 'b-ok' : 'b-warn'}">&#8226; ${p.status.toUpperCase()}</span></tr>`).join('')}</table></div>
    ${panel('POOL DETAILS CONFIGURATION', `${field('Pool Name', 'd-name', cur.name || '', 'placeholder="OFFICE_LAN"', '', 'Name used in IOS, e.g. OFFICE_LAN.')}${field('Assigned Network (CIDR)', 'd-net', cur.network ? cur.network + '/' + cur.prefix : '', 'placeholder="10.50.0.0/22"', lk('AUTO-FILL FROM CALCULATOR', 'autofill'), 'Network address with prefix — addresses are assigned from this subnet.')}<div class="mono" id="d-info" style="font-size:11px;color:#6b778c;margin:2px 0 8px;line-height:1.6"></div>
    ${field('Starting IP Address', 'd-start', '', 'placeholder="first usable host"', '', 'Leave blank to start at the first usable host.')}${field('Default Gateway', 'd-gw', cur.gateway || '', 'placeholder="first usable host"', lk('USE x.x.x.1', 'usegw'), 'Defaults to the first usable host.')}<label class="f"><span class="hl">DNS Servers<span>${chips([['Google', 'dgoogle'], ['Cloudflare', 'dcf']])}</span></span><textarea id="d-dns" rows="2" placeholder="8.8.8.8, 8.8.4.4">${esc(cur.dns || '')}</textarea></label>
    <div style="display:flex;gap:6px">${field('Lease days', 'd-ld', (cur.lease || '1 0 0').split(' ')[0], 'inputmode="numeric"')}${field('hours', 'd-lh', (cur.lease || '1 0 0').split(' ')[1], 'inputmode="numeric"')}${field('min', 'd-lm', (cur.lease || '1 0 0').split(' ')[2], 'inputmode="numeric"')}</div>
    <button class="btn wide" data-act="apply">&#9654; APPLY CHANGES</button>${cur.name ? `<button class="btn red wide" data-act="rm">&#10007; REMOVE POOL: ${esc(cur.name)}</button>` : ''}`)}</div>`;
    $$('tr[data-n]').forEach(r => r.onclick = () => { cur = pools.find(p => p.name === r.dataset.n); draw(); });
    const isNew = !cur.name;
    const m = () => {
      const c = calc(val('d-net')); const info = $('#d-info');
      if (info) info.textContent = c ? `Mask ${c.mask}  ·  Broadcast ${c.bc}  ·  Hosts ${c.first} – ${c.last}  ·  ${c.hosts} usable` : '';
      setMsg('d-net', val('d-net') && !c ? 'Enter a network like 10.50.0.0/22.' : '', true);
      if (c && isNew) { if (!val('d-gw')) $('#d-gw').value = c.first; if (!$('#d-dns').value.trim()) $('#d-dns').value = '1.1.1.1, 1.0.0.1'; }
      return c;
    }; $('#d-net').oninput = m; m();
    wire({ new: () => { cur = {}; draw(); }, rm: async () => done(await apply({ kind: 'dhcp', name: cur.name, action: 'remove' }, 'Remove pool ' + cur.name), () => vDhcp()), autofill: () => { const c = calc(S.calc); if (c) { $('#d-net').value = c.net + '/' + c.p; m(); } else toast('Enter a network in the Subnet Calculator tab first', true); },
      usegw: () => { const c = m(); if (c) $('#d-gw').value = c.first; }, dgoogle: () => $('#d-dns').value = '8.8.8.8, 8.8.4.4', dcf: () => $('#d-dns').value = '1.1.1.1, 1.0.0.1',
      apply: async () => { const c = calc(val('d-net')); if (!c) return toast('Network must look like 10.50.0.0/22', true);
        const gw = val('d-gw'); if (gw && (!isIP(gw) || ip2n(gw) < ip2n(c.net) || ip2n(gw) > ip2n(c.bc))) return toast('Gateway must be an address inside ' + c.net + '/' + c.p, true);
        const st = val('d-start'); if (st && (!isIP(st) || ip2n(st) < ip2n(c.net) || ip2n(st) > ip2n(c.bc))) return toast('Starting IP must be inside ' + c.net + '/' + c.p, true);
        done(await apply({ kind: 'dhcp', name: val('d-name'), network: c.net, mask: c.mask, gateway: val('d-gw'), dns: val('d-dns'), start_ip: val('d-start'), lease_days: val('d-ld'), lease_hours: val('d-lh'), lease_minutes: val('d-lm') }, 'DHCP pool'), () => vDhcp()); } });
  }; draw();
}

async function vVlans() {
  const vl = await api('inventory?kind=vlans'); let cur = vl[0] || {};
  const draw = () => {
    main.innerHTML = `<div class="split"><div class="panel"><div class="hl"><h3>VLAN Inventory</h3><button class="btn" data-act="new">+ CREATE NEW VLAN</button></div>
    <table><tr><th>VLAN ID<th>NAME<th>INTERFACES<th>STATUS</tr>${vl.map(v => `<tr class="clk ${v.id === cur.id ? 'sel' : ''}" data-n="${v.id}"><td>${v.id}<td class="mono">${esc(v.name)}<td class="mono">${esc(v.ports || '—')}<td><span class="badge ${v.active ? 'b-ok' : 'b-warn'}">&#8226; ${v.active ? 'ACTIVE' : 'INACTIVE'}</span></tr>`).join('')}</table></div>
    ${panel('VLAN DETAILS CONFIGURATION', `${field('VLAN ID', 'v-id', cur.id || '', 'type="number" min="1" max="4094" inputmode="numeric" placeholder="10"', lk('SUGGEST NEXT', 'next'), 'Range 1–4094; must be unique.')}${field('VLAN Name', 'v-name', cur.name || '', 'maxlength="32" placeholder="OFFICE"', '', 'Letters, digits, hyphen or underscore; 1–32 characters.')}<div>${chips([['VLAN10', 'p10'], ['MGMT', 'pm'], ['VOICE', 'pv']])}</div>
    ${field('Allowed VLANs (Trunk)', 'v-allow', '', 'placeholder="e.g. 1,10,20-30"', lk('AUTO-FILL', 'auto'))}<label class="f">Description<textarea id="v-desc" rows="3"></textarea></label><button class="btn wide" data-act="apply">+ CREATE NEW VLAN</button>${cur.id ? `<button class="btn red wide" data-act="rm">&#10007; REMOVE VLAN ${cur.id}</button>` : ''}
    <p style="font-size:10px;color:#6b778c">IOS stores only the VLAN ID and name. Allowed VLANs and Description are not pushed to the device in Sprint 1.</p>`)}</div>`;
    $$('tr[data-n]').forEach(r => r.onclick = () => { cur = vl.find(v => v.id == r.dataset.n); draw(); });
    const nameOK = v => /^[A-Za-z0-9_-]{1,32}$/.test(v);
    $('#v-id').oninput = () => setMsg('v-id', val('v-id') && !inRange(val('v-id'), 1, 4094) ? 'VLAN ID must be a whole number from 1 to 4094.' : '', true);
    $('#v-name').oninput = () => setMsg('v-name', val('v-name') && !nameOK(val('v-name')) ? 'Use 1–32 letters, digits, hyphen or underscore. No spaces.' : '', true);
    wire({ new: () => { cur = {}; draw(); }, rm: async () => done(await apply({ kind: 'vlan', vlan_id: cur.id, action: 'remove' }, 'Remove VLAN ' + cur.id), () => vVlans()), next: () => { const ids = new Set(vl.map(v => v.id)); let n = 2; while (ids.has(n)) n++; $('#v-id').value = n; },
      p10: () => { $('#v-name').value = 'VLAN10'; }, pm: () => { $('#v-name').value = 'MGMT'; }, pv: () => { $('#v-name').value = 'VOICE'; }, auto: () => { $('#v-allow').value = vl.map(v => v.id).join(','); },
      apply: async () => { if (!inRange(val('v-id'), 1, 4094)) return toast('VLAN ID must be 1–4094', true); if (!nameOK(val('v-name'))) return toast('Enter a VLAN name (1–32 letters, digits, _ or -)', true); done(await apply({ kind: 'vlan', vlan_id: val('v-id'), name: val('v-name') }, 'VLAN ' + val('v-id')), () => vVlans()); } });
  }; draw();
}

async function vRouting(tab = 'dynamic') {
  const [r, ifs] = await Promise.all([api('inventory?kind=routes'), api('inventory?kind=interfaces')]); let cur = r.dynamic[0] || {};
  const left = tab === 'dynamic' ? `<table><tr><th>PROTOCOL<th>PROCESS ID / AS<th>AREA / TAG<th>ROUTER ID<th>STATUS<th></tr>${r.dynamic.map((d, i) => `<tr class="clk ${d === cur ? 'sel' : ''}" data-i="${i}"><td style="color:#0b57d0">${d.protocol}<td>${d.process}<td>${esc(d.area)}<td class="mono">${d.router_id}<td><span class="badge b-ok">&#8226; ACTIVE</span><td><button class="link" data-act="rmd" data-p="${esc(d.protocol)}" data-id="${esc(d.process)}">Remove</button></tr>`).join('')}</table>`
    : `<table><tr><th>NETWORK<th>MASK<th>NEXT HOP<th></tr>${r.static.map(s => `<tr><td class="mono">${s.network}<td class="mono">${s.mask}<td class="mono">${s.next_hop}<td><button class="link" data-act="rms" data-net="${esc(s.network)}" data-mask="${esc(s.mask)}" data-nh="${esc(s.next_hop)}">Remove</button></tr>`).join('') || '<tr><td colspan=4>No static routes</tr>'}</table>`;
  const right = tab === 'dynamic' ? panel('DYNAMIC PROTOCOL CONFIGURATION', `<label class="f">Protocol Selection<select id="r-proto">${['OSPF', 'EIGRP', 'RIP'].map(p => `<option ${cur.protocol === p ? 'selected' : ''}>${p}</option>`).join('')}</select></label>${field('Process ID / AS', 'r-pid', cur.process || '', 'inputmode="numeric"', lk('AUTO-DETECT ID', 'autoid'))}
    <label class="f"><span class="hl">Networks to advertise${lk('PULL INTERFACES', 'pull')}</span><textarea id="r-nets" rows="3" placeholder="10.0.0.0/24">${esc((cur.networks || []).join('\n'))}</textarea></label><div id="r-areawrap">${field('Area / Tag', 'r-area', (cur.area || '0').replace('Area ', '').replace('-', '0'), 'inputmode="numeric" placeholder="0"')}<div>${chips([['Area 0', 'a0'], ['Area 1', 'a1']])}</div></div><button class="btn wide" data-act="apply">&#10003; APPLY CHANGES</button>`)
    : panel('STATIC ROUTE', `${field('Destination Network', 's-net', '', 'placeholder="10.0.0.0 or 10.0.0.0/16"', '', 'A /prefix fills the mask automatically.')}${field('Subnet Mask', 's-mask', '', 'placeholder="255.255.0.0 or /16"')}${field('Next Hop', 's-nh', '', 'placeholder="10.1.1.1"')}<button class="btn wide" data-act="applys">&#10003; ADD ROUTE</button>`);
  main.innerHTML = `<div class="split"><div class="panel"><h3>Routing Inventory</h3><div class="subtabs"><button data-act="ts" class="${tab === 'static' ? 'on' : ''}">STATIC ROUTES</button><button data-act="td" class="${tab === 'dynamic' ? 'on' : ''}">DYNAMIC ROUTING</button></div>${left}</div>${right}</div>`;
  $$('tr[data-i]').forEach(x => x.onclick = () => { cur = r.dynamic[x.dataset.i]; vRoutingDraw(); });
  const vRoutingDraw = () => vRouting(tab);
  if (tab === 'dynamic') {
    const pidHint = () => { const p = val('r-proto'); return p === 'OSPF' ? 'OSPF process ID, 1–65535.' : p === 'EIGRP' ? 'EIGRP autonomous system number, 1–65535.' : 'RIP process ID, 1–65535.'; };
    const pidCheck = () => { const v = val('r-pid'); const bad = v && !inRange(v, 1, 65535); setMsg('r-pid', bad ? 'Enter a whole number from 1 to 65535.' : pidHint(), bad); };
    const areaCheck = () => { const v = val('r-area'); if (val('r-proto') !== 'OSPF') return setMsg('r-area', '', false); const bad = v && !/^\d+$/.test(v); setMsg('r-area', bad ? 'OSPF area must be a whole number (0–4294967295).' : '', bad); };
    const protoSetup = () => { $('#r-areawrap').style.display = val('r-proto') === 'OSPF' ? '' : 'none'; pidCheck(); areaCheck(); };
    $('#r-proto').onchange = protoSetup; $('#r-pid').oninput = pidCheck; $('#r-area').oninput = areaCheck; protoSetup();
  } else {
    const netSync = () => { const c = calc(val('s-net')); if (c) { $('#s-net').value = c.net; $('#s-mask').value = c.mask; } };
    $('#s-net').onblur = netSync;
    $('#s-net').oninput = () => setMsg('s-net', val('s-net') && !calc(val('s-net')) && !isIP(val('s-net')) ? 'Enter a network like 10.0.0.0/16.' : '', true);
    $('#s-mask').onblur = () => { const p = maskPrefix(val('s-mask')); if (p != null) $('#s-mask').value = prefixMask(p); };
    $('#s-mask').oninput = () => setMsg('s-mask', val('s-mask') && maskPrefix(val('s-mask')) == null ? 'Enter 255.255.0.0 or /16.' : '', true);
    $('#s-nh').oninput = () => setMsg('s-nh', val('s-nh') && !isIP(val('s-nh')) ? 'Enter a valid next-hop IPv4 address.' : '', true);
  }
  wire({ ts: () => vRouting('static'), td: () => vRouting('dynamic'),
    rms: async e => done(await apply({ kind: 'static_route', network: e.dataset.net, mask: e.dataset.mask, next_hop: e.dataset.nh, action: 'remove' }, 'Remove route ' + e.dataset.net + (maskPrefix(e.dataset.mask) != null ? '/' + maskPrefix(e.dataset.mask) : '')), () => vRouting('static')),
    rmd: async e => done(await apply({ kind: 'dynamic_route', protocol: e.dataset.p, process: e.dataset.id, action: 'remove' }, 'Remove ' + e.dataset.p + ' ' + e.dataset.id), () => vRouting('dynamic')),
    a0: () => $('#r-area').value = 0, a1: () => $('#r-area').value = 1,
    autoid: () => { const used = new Set(r.dynamic.map(d => +d.process)); let n = 1; while (used.has(n)) n++; $('#r-pid').value = n; },
    pull: () => { $('#r-nets').value = ifs.filter(i => i.ip && i.mask).map(i => { const c = calc(i.ip + '/' + calcMask(i.mask)); return c.net + '/' + c.p; }).join('\n'); },
    apply: async () => { if (!inRange(val('r-pid'), 1, 65535)) return toast('Process ID / AS must be 1–65535', true); if (val('r-proto') === 'OSPF' && val('r-area') && !/^\d+$/.test(val('r-area'))) return toast('OSPF area must be a whole number', true); done(await apply({ kind: 'dynamic_route', protocol: val('r-proto'), process_id: val('r-pid'), networks: val('r-nets'), area: val('r-area') || 0 }, 'Dynamic routing'), () => vRouting('dynamic')); },
    applys: async () => { const c = calc(val('s-net')); const network = c ? c.net : val('s-net'); const mask = c ? c.mask : val('s-mask'); if (!isIP(network)) return toast('Destination network must be a valid IPv4 network', true); if (maskPrefix(mask) == null) return toast('Subnet mask must be dotted or a /prefix', true); if (!isIP(val('s-nh'))) return toast('Next hop must be a valid IPv4 address', true); done(await apply({ kind: 'static_route', network, mask, next_hop: val('s-nh') }, 'Static route'), () => vRouting('static')); } });
}

async function vEtherchannel() {
  const d = await api('inventory?kind=etherchannel'); let cur = d.groups[0] || {}; const phys = d.interfaces.filter(i => /^(Gigabit|Fast|Ten)/.test(i.name)); let mem = new Set(cur.interfaces || []);
  const draw = () => {
    main.innerHTML = `<div class="split"><div class="panel"><div class="hl"><h3>EtherChannel Inventory</h3><input id="q" placeholder="Search Groups..."></div><table><tr><th>GROUP ID<th>PROTOCOL<th>INTERFACES<th>MODE<th>STATUS</tr>${d.groups.map(g => `<tr class="clk ${g.group === cur.group ? 'sel' : ''}" data-g="${g.group}"><td style="color:#0b57d0">${g.po}<td>${g.protocol}<td class="mono">${g.interfaces.join(', ')}<td>${g.mode}<td><span class="badge ${g.up ? 'b-ok' : 'b-warn'}">&#8226; ${g.up ? 'IN USE (SU)' : 'DOWN (SD)'}</span></tr>`).join('')}</table></div>
    ${panel('CHANNEL GROUP DETAILS', `${field('Group Number', 'e-g', cur.group || '', 'type="number" min="1" max="48" inputmode="numeric" placeholder="1"', lk('SUGGEST NEXT', 'next'), 'Channel-group number, 1–48.')}<label class="f"><span class="hl">Protocol${lk('AUTO-SELECT BEST', 'best')}</span><select id="e-p">${['LACP', 'PAgP', 'Static'].map(p => `<option ${(cur.protocol || 'LACP') === p ? 'selected' : ''}>${p}</option>`).join('')}</select></label>
    <label class="f">Mode<select id="e-m"></select></label><div class="f"><span class="hl">Interface Membership<span>${lk('GENERATE', 'gen')} ${lk('SUGGEST BUNDLE', 'bundle')}</span></span><div id="e-ifc">${phys.map(i => `<span class="ifc ${mem.has(i.short) ? 'on' : ''}" data-if="${i.short}">${i.short}</span>`).join('')}</div><small class="hint" id="e-count"></small></div>
    <label class="f">Description<textarea id="e-d" rows="2"></textarea></label><button class="btn wide" data-act="apply">&#9654; APPLY CONFIGURATION</button>${cur.group ? `<button class="btn red wide" data-act="rm">&#10007; REMOVE CHANNEL-GROUP ${cur.group}</button>` : ''}`)}</div>`;
    const modes = () => { const p = val('e-p'); $('#e-m').innerHTML = (p === 'LACP' ? ['active', 'passive'] : p === 'PAgP' ? ['desirable', 'auto'] : ['on']).map(m => `<option ${m === (cur.mode || '').toLowerCase() ? 'selected' : ''}>${m}</option>`).join(''); }; $('#e-p').onchange = modes; modes();
    $$('tr[data-g]').forEach(r => r.onclick = () => { cur = d.groups.find(g => g.group == r.dataset.g); mem = new Set(cur.interfaces); draw(); }); search('q', 'tr[data-g]');
    const gidCheck = () => { const v = val('e-g'); const bad = v && !inRange(v, 1, 48); setMsg('e-g', bad ? 'Group number must be 1–48.' : '', bad); };
    const count = () => { const el = $('#e-count'); if (!el) return; el.textContent = mem.size >= 2 ? mem.size + ' interfaces selected.' : 'Select at least 2 interfaces (' + mem.size + ' selected).'; el.classList.toggle('bad', mem.size < 2); };
    $('#e-g').oninput = gidCheck; gidCheck(); count();
    $$('.ifc').forEach(c => c.onclick = () => { mem.has(c.dataset.if) ? mem.delete(c.dataset.if) : mem.add(c.dataset.if); c.classList.toggle('on'); count(); });
    wire({ next: () => { const u = new Set(d.groups.map(g => g.group)); let n = 1; while (u.has(n)) n++; $('#e-g').value = n; }, rm: async () => done(await apply({ kind: 'etherchannel', group: cur.group, action: 'remove' }, 'Remove channel-group ' + cur.group), () => vEtherchannel()), best: () => { $('#e-p').value = 'LACP'; modes(); },
      gen: () => { $('#e-d').value = `Po${val('e-g')} bundle: ${[...mem].join(', ')}`; }, bundle: () => { const free = phys.filter(i => !i.channel).slice(0, 2).map(i => i.short); mem = new Set(free); draw(); },
      apply: async () => { if (!inRange(val('e-g'), 1, 48)) return toast('Group number must be 1–48', true); if (mem.size < 2) return toast('Select at least 2 member interfaces', true); done(await apply({ kind: 'etherchannel', group: val('e-g'), protocol: val('e-p'), mode: val('e-m'), interfaces: [...mem], description: val('e-d') }, 'EtherChannel'), () => vEtherchannel()); } });
  }; draw();
}

async function vPortsec() {
  const ifs = await api('inventory?kind=portsec'); const sel = new Set(ifs[0] ? [ifs[0].short] : []); let pol = { max: 1, violation: 'shutdown', sticky: true };
  const draw = () => {
    const first = ifs.find(i => sel.has(i.short)); if (first && first.portsec.enabled) pol = { max: first.portsec.max, violation: first.portsec.violation, sticky: first.portsec.sticky };
    main.innerHTML = `<div class="split"><div class="panel"><div class="hl"><h3>Interface Security Inventory</h3><input id="q" placeholder="Filter interfaces..."></div><table><tr><th>INTERFACE<th>SECURITY<th>MAX MACS<th>VIOLATION MODE<th>VIOLATIONS</tr>${ifs.map(i => `<tr class="clk ${sel.has(i.short) ? 'sel' : ''}" data-i="${i.short}"><td style="color:#0b57d0">${i.short}<td><span class="tog ${i.portsec.enabled ? 'on' : ''}"></span><td>${i.portsec.enabled ? i.portsec.max : '-'}<td>${i.portsec.enabled ? `<span class="badge ${i.portsec.violation === 'shutdown' ? 'b-warn' : 'b-info'}">${i.portsec.violation.toUpperCase()}</span>` : 'Disabled'}<td>${i.violations ? `<span class="crit">&#9888; ${i.violations}</span>` : i.portsec.enabled ? 0 : '-'}</tr>`).join('')}</table></div>
    ${panel('&#128737; POLICY CONFIG <a class="link" style="float:right;color:#fff" data-act="auto">AUTO-SECURE</a>', `<label class="f">Selected Target<input readonly value="${sel.size > 1 ? 'Multiple (' + sel.size + ' selected)' : [...sel][0] || ''}"></label>${field('Max MAC Addresses', 'p-max', pol.max, 'type="number" min="1" max="8192" inputmode="numeric"', '', 'Secure MAC address limit, 1–8192.')}
    <label class="f">Violation Mode</label><div class="seg">${['protect', 'restrict', 'shutdown'].map(v => `<button data-v="${v}" class="${pol.violation === v ? 'on' : ''}">${v.toUpperCase()}</button>`).join('')}</div><small class="hint">protect drops silently · restrict drops and logs · shutdown err-disables the port.</small>
    <div class="hl" style="margin:8px 0"><span><b>STICKY MAC LEARNING</b><br><small>Save dynamic MACs to running-config</small></span><span class="tog ${pol.sticky ? 'on' : ''}" id="p-st"></span></div><button class="btn wide" data-act="apply">&#10003; APPLY CONFIGURATION</button>
    <button class="btn red wide" data-act="off">DISABLE PORT SECURITY ON SELECTION</button>`)}</div>`;
    $$('tr[data-i]').forEach(r => r.onclick = () => { const k = r.dataset.i; sel.has(k) ? sel.delete(k) : sel.add(k); draw(); }); search('q', 'tr[data-i]');
    const pmaxCheck = () => { const v = val('p-max'); const bad = v && !inRange(v, 1, 8192); setMsg('p-max', bad ? 'Max MACs must be a whole number from 1 to 8192.' : '', bad); };
    $('#p-max').oninput = pmaxCheck; pmaxCheck();
    $$('.seg button').forEach(b => b.onclick = () => { pol.violation = b.dataset.v; $$('.seg button').forEach(x => x.classList.toggle('on', x === b)); }); $('#p-st').onclick = () => { pol.sticky = !pol.sticky; $('#p-st').classList.toggle('on', pol.sticky); };
    const go = async en => { if (en && !inRange(val('p-max'), 1, 8192)) return toast('Max MACs must be 1–8192', true); done(await apply({ kind: 'portsec', interfaces: [...sel], enabled: en, max_mac: val('p-max'), violation: pol.violation, sticky: pol.sticky }, 'Port security'), () => vPortsec()); };
    wire({ auto: () => { pol = { max: 1, violation: 'shutdown', sticky: true }; draw(); }, apply: () => go(true), off: () => go(false) });
  }; draw();
}

// ---- Devices ----------------------------------------------------------
async function pageDevices() {
  let rows = await api('devices'), pg = 1, open = null; const PER = 10;
  const draw = () => {
    const q = val('dq').toLowerCase(), st = val('ds') || 'All Statuses', ty = val('dt') || 'All Devices';
    const f = rows.filter(r => (!q || r.name.toLowerCase().includes(q)) && (st === 'All Statuses' || r.status === st) && (ty === 'All Devices' || r.platform === ty));
    const types = [...new Set(rows.map(r => r.platform).filter(Boolean))], page = f.slice((pg - 1) * PER, pg * PER), pages = Math.max(1, Math.ceil(f.length / PER));
    main.innerHTML = `<div class="filters"><input id="dq" class="grow" placeholder="Search by hostname..." value="${esc(q)}"><span>Filter by Status:</span><select id="ds">${['All Statuses', 'Up', 'Down'].map(s => `<option ${s === st ? 'selected' : ''}>${s}</option>`).join('')}</select><span>Filter by Type:</span><select id="dt"><option>All Devices</option>${types.map(t => `<option ${t === ty ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
    <div class="panel"><table><tr><th>STATUS<th>HOSTNAME<th>MANAGEMENT IP<th>PLATFORM<th>VERSION<th>LAST CHECK-IN<th>ACTIONS</tr>${page.map(r => `<tr class="clk" data-id="${r.id}"><td><span class="badge ${r.status === 'Up' ? 'b-ok' : 'b-warn'}">&#8226; ${r.status.toUpperCase()}</span><td style="color:#0b57d0">${esc(r.name)}${r.selected ? ' <span class="badge b-info">ACTIVE</span>' : ''}<td class="mono">${esc(r.host)}<td>${esc(r.platform)}<td>${esc(r.version)}<td>${esc(r.last_check)}<td><button class="link" data-chk="${r.id}">CHECK</button> <button class="link" data-use="${r.id}">USE</button></tr>
    ${open === r.id ? `<tr><td colspan="7" style="background:#f6f9ff"><div class="row2" style="grid-template-columns:1fr 2fr"><div><b>NETWORK CONFIGURATION</b><p class="mono">Hostname: ${esc(r.name)}<br>Mgmt Interface: ${esc(r.mgmt_if || '-')}<br>SSH Port: 22</p></div><div><b>OPERATIONAL COMMANDS</b><div class="opcmd" style="margin-top:6px">${[['Show Interfaces', 'show interfaces status'], ['Show VLAN', 'show vlan brief'], ['Show MAC Address Table', 'show mac address-table'], ['Show EtherChannel', 'show etherchannel summary'], ['Show IP Route', 'show ip route'], ['Show STP Status', 'show spanning-tree summary']].map(c => `<button data-cmd="${c[1]}">${c[0]}</button>`).join('')}</div></div></div><pre id="op-out" class="term" style="max-height:200px;display:none"></pre><div style="text-align:right"><button class="btn red sm" data-del="${r.id}">DELETE DEVICE</button></div></tr>` : ''}`).join('') || '<tr><td colspan="7">No devices yet. Use SSH Access on the General page to connect one.</tr>'}</table>
    <div class="pg"><span>Showing ${f.length ? (pg - 1) * PER + 1 : 0}-${Math.min(pg * PER, f.length)} of ${f.length} entries</span><span><button data-pg="${pg - 1}" ${pg < 2 ? 'disabled' : ''}>Prev</button> ${Array.from({ length: pages }, (_, i) => `<button class="${i + 1 === pg ? 'on' : ''}" data-pg="${i + 1}">${i + 1}</button>`).join(' ')} <button data-pg="${pg + 1}" ${pg >= pages ? 'disabled' : ''}>Next</button></span></div></div>`;
    ['dq', 'ds', 'dt'].forEach(i => $('#' + i).oninput = () => { pg = 1; const p = $('#dq').selectionStart; draw(); const e = $('#dq'); if (i === 'dq') { e.focus(); e.setSelectionRange(p, p); } });
    $$('tr[data-id]').forEach(r => r.onclick = e => { if (e.target.closest('button')) return; open = open === +r.dataset.id ? null : +r.dataset.id; draw(); });
    $$('[data-pg]').forEach(b => b.onclick = () => { pg = +b.dataset.pg; draw(); });
    $$('[data-use]').forEach(b => b.onclick = () => busy(b, async () => { await api('device/select', { id: +b.dataset.use }); location.reload(); }));
    $$('[data-chk]').forEach(b => b.onclick = () => busy(b, async () => { const r = await api('device/check', { id: +b.dataset.chk }); toast(r.ok ? 'Device is Up' : 'Device is Down', !r.ok); rows = await api('devices'); draw(); }));
    $$('[data-del]').forEach(b => b.onclick = () => busy(b, async () => { if (confirm('Delete this device and its backups?')) { await api('device/delete', { id: +b.dataset.del }); rows = await api('devices'); open = null; draw(); } }));
    $$('[data-cmd]').forEach(b => b.onclick = () => busy(b, async () => { const o = $('#op-out'); o.style.display = 'block'; o.textContent = 'running ' + b.dataset.cmd + ' ...'; try { o.textContent = (await api('device/show', { id: open, command: b.dataset.cmd })).output; } catch (e) { o.textContent = e.message; } }));
  }; draw();
}

// ---- Logs -------------------------------------------------------------
async function pageLogs() {
  let tab = 'audit', rows = await api('audit');
  const draw = () => {
    if (tab === 'sev') { main.innerHTML = `<div class="subtabs"><button data-t="sev" class="on">Severity Logs</button><button data-t="audit">Audit Logs (Command History)</button></div><div class="panel"><table><tr><th>TIMESTAMP<th>DEVICE<th>FACILITY<th>SEVERITY<th>MESSAGE<th>THREAT</tr><tr><td colspan="6">Syslog collection and threat flagging are delivered in Sprint 4. No syslog data is received yet.</tr></table></div>`; }
    else { const q = val('lq').toLowerCase(); const f = rows.filter(r => !q || (r.action + r.username + r.device_host).toLowerCase().includes(q));
      main.innerHTML = `<div class="subtabs"><button data-t="sev">Severity Logs</button><button data-t="audit" class="on">Audit Logs (Command History)</button></div><div class="filters"><input id="lq" class="grow" placeholder="Search logs..." value="${esc(q)}"><span>TOTAL LOGS <b>${f.length}</b></span><button class="btn red sm" id="lclr">CLEAR LOGS</button><button class="btn blue sm" id="lref">&#8635;</button></div>
      <div class="panel"><table><tr><th>TIMESTAMP<th>DEVICE<th>ADMIN/USERNAME<th>ACTION/COMMAND MADE</tr>${f.map(r => `<tr><td class="mono">${esc(r.at)}<td class="mono" style="color:#0b57d0">${esc(r.device_host || '')}<td>${esc(r.username)}<td class="mono">${esc(r.action)}</tr>`).join('') || '<tr><td colspan="4">No log entries</tr>'}</table></div>`;
      $('#lq').oninput = () => { const p = $('#lq').selectionStart; draw(); $('#lq').focus(); $('#lq').setSelectionRange(p, p); };
      $('#lclr').onclick = () => busy($('#lclr'), async () => { if (confirm('Clear all audit logs?')) { await api('audit_clear', {}); rows = await api('audit'); draw(); } }); $('#lref').onclick = () => busy($('#lref'), async () => { rows = await api('audit'); draw(); }); }
    $$('.subtabs button').forEach(b => b.onclick = () => { tab = b.dataset.t; draw(); });
  }; draw();
}

boot().catch(e => { if (e.message !== 'signed out') main.innerHTML = `<div class="panel err">${esc(e.message)}</div>`; });
})();
