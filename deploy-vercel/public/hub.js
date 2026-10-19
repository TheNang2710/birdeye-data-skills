const $ = id => document.getElementById(id);
const APP_PAGE = document.body?.dataset?.page || 'home';

// ---- Copy-to-clipboard for wallet/token addresses in rendered output ----
document.addEventListener('click', async (ev) => {
  const el = ev.target.closest?.('[data-copy-addr]');
  if (!el) return;
  ev.preventDefault();
  const val = (el.getAttribute('data-copy-addr') || '').trim();
  if (!val) return;
  const origHTML = el.innerHTML;
  try {
    await navigator.clipboard.writeText(val);
    el.innerHTML = origHTML.replace(/📋/, '✅');
  } catch (_) {
    try {
      const ta = document.createElement('textarea');
      ta.value = val; ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); document.body.removeChild(ta);
      el.innerHTML = origHTML.replace(/📋/, '✅');
    } catch (__) {
      el.innerHTML = origHTML.replace(/📋/, '✗');
    }
  }
  setTimeout(() => { el.innerHTML = origHTML; }, 1200);
});
let CATALOG = [];
async function loadCatalog(){
  if(Array.isArray(CATALOG) && CATALOG.length) return CATALOG;
  try{
    if(window.CATALOG_JSON_RAW){
      CATALOG = JSON.parse(window.CATALOG_JSON_RAW || '[]');
      return CATALOG;
    }
  }catch(_){}
  // Live hub endpoint first, then the static catalog shipped with the deploy.
  for(const src of ['/api/catalog', '/catalog.json']){
    try{
      const r = await fetch(src, {cache:'no-store'});
      if(!r.ok) continue;
      const j = await r.json();
      const items = Array.isArray(j) ? j : j.items;
      if(Array.isArray(items) && items.length){ CATALOG = items; return CATALOG; }
    }catch(_){}
  }
  CATALOG = [];
  return CATALOG;
}
function buildHomeUrl(filter='all'){
  const q = new URLSearchParams();
  if(filter && filter !== 'all') q.set('filter', filter);
  const s = q.toString();
  return s ? '/?'+s : '/';
}
function buildDetailUrl(skillId, catId){
  const q = new URLSearchParams();
  if(skillId) q.set('skill', skillId);
  if(catId) q.set('cat', catId);
  return '/detail?' + q.toString();
}
const LSKEY_SESSION_PASTE = 'be.key.paste';

function ensureGlobalKeyCollapse(){
  const wrap = $('g_key');
  if(!wrap || wrap.dataset.collapsedReady === '1') return;
  const title = wrap.querySelector('h3');
  const keyInfo = $('keyInfo');
  const keyActions = $('keyActions');
  if(!title || !keyInfo || !keyActions) return;

  const details = document.createElement('details');
  details.className = 'apiCollapseGlobal';
  details.style.border = '1px solid var(--line)';
  details.style.borderRadius = '10px';
  details.style.background = 'var(--panel)';

  const summary = document.createElement('summary');
  summary.style.listStyle = 'none';
  summary.style.cursor = 'pointer';
  summary.style.padding = '10px 12px';
  summary.style.display = 'flex';
  summary.style.alignItems = 'center';
  summary.style.justifyContent = 'space-between';
  summary.style.gap = '10px';

  const left = document.createElement('span');
  left.style.fontWeight = '700';
  left.textContent = title.textContent || '🔑 API Key';

  keyInfo.classList.add('subtle');
  keyInfo.style.fontSize = '11px';
  keyInfo.style.textAlign = 'right';
  keyInfo.style.marginLeft = 'auto';

  summary.appendChild(left);
  summary.appendChild(keyInfo);

  const body = document.createElement('div');
  body.style.padding = '0 12px 12px';
  body.appendChild(keyActions);

  details.appendChild(summary);
  details.appendChild(body);

  wrap.innerHTML = '';
  wrap.appendChild(details);
  wrap.dataset.collapsedReady = '1';
}
// ---- Category metadata helpers (derive stable ids + short descriptions from catalog) ----
function catIdOf(g){
  // 🔥 Discovery (3) → discovery; 🛡 Token Due Diligence (5) → token-dd
  if(!g || !g.cat) return 'cat'+Math.random();
  const t = (g.cat||'').replace(/^[\W_]+|[\W_]+$/g,'');
  const stem = t.split('(')[0].trim().toLowerCase();
  const base = stem.replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');
  if(base === 'discovery') return 'discovery';
  if(base.startsWith('token-due-diligence')) return 'token-dd';
  if(base.startsWith('wallet-smart-money')) return 'smart-money';
  if(base.startsWith('security-risk')) return 'security-risk';
  if(base.startsWith('chain-platform')) return 'chain-platform';
  if(base.startsWith('history-charts')) return 'history-charts';
  if(base.startsWith('alerts-bots')) return 'alerts-bots';
  if(base.startsWith('utils-settings')) return 'utils-settings';
  return base || 'cat';
}
function catTitle(g){
  var s = (g.cat||'').replace(/\s*\(\d+\)\s*$/,'').trim();
  // Strip leading emoji / symbols + spaces until first Latin letter/digit.
  // Latin cap = U+024F (591, end of Latin Extended B) — intentionally excludes
  // dingbats/symbols (U+2600..) like ⛓🧠🛡 which are >= 192 but NOT letters.
  var firstIdx = -1;
  for(var i=0;i<s.length;i++){
    var cc = s.charCodeAt(i);
    var latin =
      (cc>=48 && cc<=57)   ||  // 0-9
      (cc>=65 && cc<=90)   ||  // A-Z
      (cc>=97 && cc<=122)  ||  // a-z
      (cc>=192 && cc<=0x024F); // Latin 1/Ext-A/Ext-B accented letters only
    if(latin){ firstIdx = i; break; }
    // Skip 2nd unit of surrogate pairs (emoji chars span 2 UTF-16 code units)
    if(cc>=0xD800 && cc<=0xDBFF){ i++; }
  }
  if(firstIdx>0){ s = s.substring(firstIdx).trim(); }
  return s;
}
function catCount(g){ return (g.items||[]).length; }
function catIcon(g){
  const c = catIdOf(g);
  return ({discovery:'🔥','token-dd':'🛡','smart-money':'🧠','security-risk':'🔐','chain-platform':'⛓','history-charts':'📈','alerts-bots':'🤖','utils-settings':'⚙'}[c]) || '📂';
}
function catShortDesc(g){
  const c = catIdOf(g);
  return ({discovery:'Find hot tokens fast — sorted volume, new pairs, launch platforms.',
    'token-dd':'Due diligence scorecard — security, price, smart money, verdict.',
    'smart-money':'Follow smart trader wallets, portfolios, flows, copy-trade setup.',
    'security-risk':'Rug risk, LP locks, KOL/dev social links audits.',
    'chain-platform':'Cross-chain compare, launchpad filter, meme basket health.',
    'history-charts':'Long-term price, volume distribution, catalysts, correlations.',
    'alerts-bots':'Volume surge rules + Telegram-ready signal payloads.',
    'utils-settings':'API key management, CU billing monitor, docs / source links.'}[c]) || ((g.items||[]).map(i=>i.title).join(', ').substring(0,120));
}
// ---- Global state ----
window.STATE = {mode: APP_PAGE==='detail' ? 'drill' : 'home', homeView:'card', homeFilter:'all', skill:null, selection:null, lastRun:null,
  activeCategory:null, collapsed:{}};

function headTail(s,h=6,t=4){ if(!s) return ''; if(s.length<=h+t+3) return s; return s.slice(0,h)+'…'+s.slice(-t); }

// ---------- Preflight format validation (0-CU; FAIL = NO /api/run POST) ----------
const SOL_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const EVM_RE = /^0x[a-fA-F0-9]{40}$/;
function validateSolAddr(a){ return !!(a && typeof a==='string' && SOL_RE.test(a.trim())); }
function validateEVMAddr(a){ return !!(a && typeof a==='string' && EVM_RE.test(a.trim())); }
function validateAnyAddr(a, chain){
  const t = (a||'').trim();
  if(!t) return {ok:false, msg:'Address required.'};
  if(!chain || chain==='sol'){ if(!validateSolAddr(t)) return {ok:false, msg:'Invalid Solana address (base58, 32-44 chars).'}; }
  else { if(!validateEVMAddr(t)) return {ok:false, msg:'Invalid EVM address (0x + 40 hex).'}; }
  return {ok:true};
}
function validateNumberRange(val, min, max, label){
  if(val==='' || val==null) return {ok:false, msg: (label||'Value')+' required.'};
  const n = Number(val);
  if(!isFinite(n)) return {ok:false, msg: (label||'Value')+' must be numeric.'};
  if(n<min || n>max) return {ok:false, msg: (label||'Value')+' must be between '+min+' and '+max+'.'};
  return {ok:true};
}
function validateEnum(val, allowed, label){
  if(!allowed.includes(val)) return {ok:false, msg:(label||'Field')+' invalid. Allowed: '+allowed.join(', ')};
  return {ok:true};
}
// Cache key-set state every 30s so preflight doesn't hammer server
const _KEY_CACHE = {ts:0, key_set:false, mask:''};
async function _keySetOk(){
  const now = Date.now();
  if(now - _KEY_CACHE.ts < 30000) return _KEY_CACHE.key_set;
  try{
    const j = await api('/api/key-info');
    _KEY_CACHE.ts = now; _KEY_CACHE.key_set = !!j.key_set; _KEY_CACHE.mask = j.mask||'';
    return _KEY_CACHE.key_set;
  }catch(e){ return false; }
}

const _SKILL_DOC_MAP = {
  tl:'07-smart-money-token-list.md', tl_v3:'07-smart-money-token-list.md',
  dd:'10-composite-dd-10step.md',
  new_pair:'01-token-overview.md', security:'03-token-security.md', contract_dd:'02-chart-ohlcv-liquidity.md',
  stc:'04-holder-distribution.md', compare:'02-chart-ohlcv-liquidity.md',
  sm_tokens:'07-smart-money-token-list.md', sm_wallets:'11-smart-traders-criteria-skill9.md',
  wallet_portfolio:'06-top-traders-profile.md', wallet_style:'06-top-traders-profile.md',
  wallet_money_flow:'06-top-traders-profile.md', wallet_score:'06-top-traders-profile.md',
  sm_flow_token:'06-top-traders-profile.md', rug_score:'12-rugcheck-risk-audit-skill17b.md',
  lp_check:'03-token-security.md', kols:'05-holder-profile-top20.md',
  rugcheck_risk_audit:'12-rugcheck-risk-audit-skill17b.md', chains:'02-chart-ohlcv-liquidity.md',
  pf_tokens:'04-holder-distribution.md', meme_index:'08-trade-data-aggregates.md',
  kline_pattern:'02-chart-ohlcv-liquidity.md', contract_dd:'03-token-security.md',
  price_1y:'02-chart-ohlcv-liquidity.md',
  vol_profile:'08-trade-data-aggregates.md', corr_map:'02-chart-ohlcv-liquidity.md',
  events:'09-fee-mint-burn-events.md', alert_surge:'08-trade-data-aggregates.md',
  tg_signal:'08-trade-data-aggregates.md', billing:'08-trade-data-aggregates.md'
};
function openApiDocForSkill(id){
  const f = _SKILL_DOC_MAP[id] || '10-composite-dd-10step.md';
  window.open('/API/'+f, '_blank');
}

function _skillViews(id){ try { return parseInt(localStorage.getItem('be.sk.views.'+id)||'0',10)||0; } catch(e){ return 0; } }
function _skillRuns(id){ try { return parseInt(localStorage.getItem('be.sk.runs.'+id)||'0',10)||0; } catch(e){ return 0; } }

// ================== HOME / HUB view ==================
function renderHome(){
  if(APP_PAGE === 'home'){
    window.history.replaceState({}, '', buildHomeUrl(window.STATE.homeFilter || 'all'));
  }
  // Banner adjustments
  $('goHubBtn').style.display = 'none';
  const bc = $('breadcrumb'); bc.style.display = 'none'; bc.innerHTML = '';
  $('homeView').style.display = '';
  $('drillView').style.display = 'none';
  // Compose
  const v = window.STATE.homeView || 'card';
  const f = window.STATE.homeFilter || 'all';
  const total = CATALOG.reduce((s,g)=>s+catCount(g),0);
  const liveTotal = CATALOG.reduce((s,g)=>s+(g.items.filter(i=>i.status==='live').length),0);

  // ==== Filter bar (9 chips: All + 8 cats) ====
  let fbar = '<div class="filterBar">';
  fbar += `<button data-id="all" class="chipBtn ${f==='all'?'on':''}" onclick="window.STATE.homeFilter='all';renderHome()">🌐 All</button>`;
  CATALOG.forEach(function(g){
    const id = catIdOf(g);
    const on = (f===id) ? ' on' : '';
    const ic = catIcon(g);
    const tt = catTitle(g);
    fbar += `<button data-id="${id}" class="chipBtn${on}" onclick="window.STATE.homeFilter='${id}';renderHome()">${ic} ${htmlEscape(tt)}</button>`;
  });
  fbar += '</div>';

  // ==== NEW v3: Flatten ALL 32 skills → per-skill cards. Filter by f if needed. ====
  let itemsAll = [];
  CATALOG.forEach(function(g, gIdx){
    const cId = catIdOf(g);
    if (f==='all' || f===cId) {
      g.items.forEach(function(it, sIdx){ itemsAll.push(Object.assign({}, it, {_catId:cId, _gIdx:gIdx})); });
    }
  });
  let gFound = f==='all' ? null : CATALOG.find(g=>catIdOf(g)===f) || null;

  let bodyHtml = '';
  if (!itemsAll.length) {
    bodyHtml = `<div class="cats"><div class="catCard"><div class="catDesc">No skills match filter: ${htmlEscape(f)}</div></div></div>`;
  } else {
    bodyHtml = `
      <div class="cats skillCardGrid32" style="grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px">
        ${itemsAll.map((it)=>{
          const st = it.status==='live'?'LIVE':'WIP';
          const stClass = it.status==='live'?'live':'wip';
          const cu = it.cu || '?';
          const gObj = CATALOG[it._gIdx] || {cat:''};
          const catIconStr = catIcon(gObj);
          const catName = catTitle(gObj);
          const views = _skillViews(it.id);
          const runs = _skillRuns(it.id);
          const btnLabel = it.status==='live' ? 'Open' : 'Detail';
          const btnClass = it.status==='live' ? 'btn primary' : 'btn';
          return `<div class="skillCard" data-cat="${it._catId}" data-idx="${it._gIdx}" data-skill="${it.id}">
            <div class="sHead">
              <span class="sIcon" style="font-size:32px;min-width:52px;height:52px;display:flex;align-items:center;justify-content:center;background:var(--deep-bg);border-radius:12px;border:1px solid var(--line)">${catIconStr}</span>
              <div style="display:flex;flex-direction:column;gap:6px;min-width:0">
                <span class="sTitle" style="font-size:16px;font-weight:700;line-height:1.25">${htmlEscape(it.title)}</span>
                <div class="sBadges" style="display:flex;flex-wrap:wrap;gap:6px;margin:0">
                  <span class="tag ${stClass}" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">${st}</span>
                  <span class="sPill"><span class="tag birdeye" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">🛰 Birdeye Data</span></span>
                  <span class="sPill"><span class="tag" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">📂 ${htmlEscape(catName)}</span></span>
                </div>
              </div>
            </div>
            <div class="sDesc" style="margin-top:14px;font-size:13px;line-height:1.55;color:var(--mute)">${htmlEscape(it.desc||'Short description coming soon.')}</div>
            <div class="sMetrics" style="margin-top:14px;display:flex;gap:16px">
              <span class="sMet" style="font-size:12px;color:var(--mute);font-weight:600">👁 ${fmtUsd(views)}</span>
              <span class="sMet" style="font-size:12px;color:var(--mute);font-weight:600">↓ ${fmtUsd(runs)}</span>
            </div>
            <div class="sFoot" style="margin-top:16px;display:flex;align-items:center;justify-content:space-between">
              <span class="sCu" title="Compute Unit cost per run" style="font-weight:700;font-size:12px;background:var(--tag);padding:4px 10px;border-radius:999px">⚡${cu} CU</span>
              <button class="${btnClass} sDetail" data-act="${it.status==='live'?'run':'detail'}">${btnLabel}</button>
            </div>
          </div>`;
        }).join('')}
      </div>`;
  }

  const _catHero = {
    discovery: '🔥 Scan the market — new tokens, 5-min movers, and fast trending lists.',
    'token-dd': '🛡 Should I buy this token? 10-step risk, security & smart-money verdict.',
    'smart-money': '🧠 Follow proven trader wallets — flows, portfolios, copy-trade setups.',
    'security-risk': '🔐 Rug risk audits — LP locks, concentrations, dev/KOL links.',
    'chain-platform': '⛓ Cross-chain scan + launchpad filtering + meme basket health.',
    'history-charts': '📈 Long-term price, volume distribution + event catalysts.',
    'alerts-bots': '🤖 Telegram signals + volume surge rule engines.',
    'utils-settings': '⚙ API key management, billing CU monitor, docs / source links.'
  };
  const heroText = (f==='all')
    ? '🛰 Birdeye Data Skills · 32 on-chain trading superpowers. Data-first. Agent-ready. Run anything in one click.'
    : _catHero[f] || (() => { const g = CATALOG.find(x=>catIdOf(x)===f); return g ? catIcon(g)+' '+htmlEscape(catTitle(g))+' — curated on-chain skill set.' : ''; })();

  // 4 sections only when f==='all' (home unfiltered); skip A/B/C on filtered cat view (just D Skills Hub)
  let secA = '', secB = '', secC = '';
  if(f === 'all'){
    secA = `
    <!-- ============ A · HERO SECTION ============ -->
    <section class="homeHero" style="padding:28px 0 10px;position:relative">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap">
        <img id="homeLogo" src="/assets/birdeye-logo-official-dark.png" alt="Birdeye" style="height:42px;object-fit:contain;filter:drop-shadow(0 2px 10px rgba(0,0,0,.25))" />
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
          <span class="pillr" style="background:var(--tag);border:1px solid var(--line);font-weight:700;padding:6px 12px;border-radius:999px">🛰 32 Skills</span>
          <span class="pillr" style="background:var(--tag);border:1px solid var(--line);font-weight:700;padding:6px 12px;border-radius:999px;color:var(--good)">🟢 ${liveTotal} LIVE</span>
          <span class="pillr" style="background:var(--tag);border:1px solid var(--line);font-weight:700;padding:6px 12px;border-radius:999px">📚 12 API modules</span>
          <span class="pillr" style="background:var(--tag);border:1px solid var(--line);font-weight:700;padding:6px 12px;border-radius:999px">⛓ 4 Chains</span>
          <div style="width:1px;height:20px;background:var(--line);margin:0 4px"></div>
          <a class="btn ghost" href="https://data.birdeye.so/docs/llms.txt" target="_blank" rel="noopener" style="padding:6px 12px;font-size:12px;text-decoration:none;font-weight:600">📘 Docs ↗</a>
        </div>
      </div>
      <h1 style="font-size:30px;font-weight:800;margin:0 0 10px;line-height:1.2;letter-spacing:-.3px">On-chain data superpowers.<br/><span style="background:linear-gradient(90deg,#6aa6ff,#2ecc71);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">Data-first · Agent-ready.</span></h1>
      <p style="font-size:15px;color:var(--mute);margin:0;line-height:1.65;max-width:780px">32 production-grade skills powered by Birdeye Data API. Discovery → Token Due Diligence → Wallet Intelligence → Risk Audits → Alerts. Build anything in one click.</p>
    </section>`;

    secB = `
    <!-- ============ B · SETUP SECTION (2 cards — AI BYO + CLI install) ============ -->
    <section style="padding:20px 0">
      <div class="homeSecHead" style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <h2 style="font-size:18px;font-weight:700;margin:0">📦 Quick Setup</h2>
        <div style="flex:1"></div>
        <span class="subtle" style="font-size:12px">2 minutes end-to-end</span>
      </div>
      <div class="homeSec2" style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px">
        <!-- B1 · AI Provider BYO Key (Skill #28 entry) -->
        <div class="skillCard" style="padding:20px 22px;gap:14px;min-height:auto">
          <div style="display:flex;align-items:center;gap:10px"><span style="font-size:26px">🤖</span><h3 style="margin:0;font-size:15px;font-weight:700">Bring Your Own LLM</h3></div>
          <div class="subtle" style="font-size:12px;line-height:1.55">Chat with an agent that knows all 32 skills. Supports OpenAI / Anthropic / OpenRouter / Gemini. Manage keys via Skill #28 → AI BYO tab.</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn primary" onclick="window.location.href=buildDetailUrl('key','utils-settings')" style="padding:6px 12px;font-size:12px;font-weight:700">🔧 Open Key Manager (#28)</button>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:2px">
            <span class="pillr" style="padding:3px 9px;font-size:11px;background:var(--tag);border:1px solid var(--line);border-radius:999px">OpenAI</span>
            <span class="pillr" style="padding:3px 9px;font-size:11px;background:var(--tag);border:1px solid var(--line);border-radius:999px">Anthropic</span>
            <span class="pillr" style="padding:3px 9px;font-size:11px;background:var(--tag);border:1px solid var(--line);border-radius:999px">OpenRouter</span>
            <span class="pillr" style="padding:3px 9px;font-size:11px;background:var(--tag);border:1px solid var(--line);border-radius:999px">Gemini</span>
          </div>
        </div>
        <!-- B2 · CLI Install (3 steps, copy cmd) -->
        <div class="skillCard" style="padding:20px 22px;gap:14px;min-height:auto">
          <div style="display:flex;align-items:center;gap:10px"><span style="font-size:26px">⚡</span><h3 style="margin:0;font-size:15px;font-weight:700">CLI Install (3 steps)</h3></div>
          <div class="subtle" style="font-size:12px;line-height:1.55">Python stdlib zero-dependency. Git clone → CD root → run server on port 8765. No npm/pip install required.</div>
          <pre id="homeCmd" style="margin:0;padding:12px;border-radius:10px;background:var(--deep-bg);border:1px solid var(--line);font-size:11.5px;font-family:monospace;color:var(--text);white-space:pre-wrap;line-height:1.7;cursor:pointer;user-select:all" title="Click to copy all lines to clipboard">git clone https://github.com/TheNang2710/birdeye-data-skills.git
cd birdeye-data-skills
./server.sh start            # → http://127.0.0.1:8765  (landing + /test console)</pre>
          <div style="display:flex;gap:8px;align-items:center;justify-content:space-between">
            <span id="homeCopyMsg" class="subtle" style="font-size:11px">⬆ click box to copy to clipboard</span>
            <button class="btn ghost" id="homeCopyBtn" style="padding:6px 12px;font-size:12px">📋 Copy</button>
          </div>
        </div>
      </div>
    </section>`;

    secC = `
    <!-- ============ C · LIVE DEMOS · click card → open Run panel ============ -->
    <section style="padding:10px 0">
      <div class="homeSecHead" style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <h2 style="font-size:18px;font-weight:700;margin:0">🎬 Live Demos</h2>
        <div style="flex:1"></div>
        <span class="subtle" style="font-size:12px">Click any card → opens the dedicated detail page · then hit ▶ Run</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px" class="homeShowGrid">
        <!-- Demo 1 · V3 Trending List -->
        <div class="skillCard demoCard" data-cat="discovery" data-idx="${CATALOG.findIndex(g=>catIdOf(g)==='discovery')}" data-skill="tl_v3" data-act="run" style="padding:22px;gap:14px;min-height:auto;cursor:pointer">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:30px">🔥</span>
            <div style="display:flex;flex-direction:column;gap:4px;min-width:0">
              <h3 style="margin:0;font-size:16px;font-weight:800">V3 Trending List</h3>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <span class="tag live" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">LIVE</span>
                <span class="tag birdeye" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">🛰 Birdeye Data</span>
                <span class="tag" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">⚡ 50 CU</span>
              </div>
            </div>
          </div>
          <div style="font-size:13px;line-height:1.6;color:var(--mute)">Accurate V3 token list. Filter by min_volume ($), liquidity bands, trade intervals, sort by volumeUSD descending. All numeric ranges in one panel.</div>
          <div style="display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:4px">
            <span class="pillr" style="padding:4px 10px;font-size:11px;background:var(--good-bg);border:1px solid var(--good);color:var(--good);border-radius:999px;font-weight:700">▶ Click card → Run panel opens · then ▶ Run (50 CU)</span>
            <span style="font-weight:700;font-size:12px;color:var(--mute)">Skill #1b</span>
          </div>
        </div>
        <!-- Demo 2 · Token DD (featured — accent border) -->
        <div class="skillCard demoCard" data-cat="token-dd" data-idx="${CATALOG.findIndex(g=>catIdOf(g)==='token-dd')}" data-skill="dd" data-act="run" style="padding:22px;gap:14px;min-height:auto;cursor:pointer;border:2px solid var(--accent)">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:30px">🛡</span>
            <div style="display:flex;flex-direction:column;gap:4px;min-width:0">
              <h3 style="margin:0;font-size:16px;font-weight:800">Token Due Diligence</h3>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <span class="tag live" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">LIVE</span>
                <span class="tag birdeye" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">🛰 Birdeye Data</span>
                <span class="tag" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">⚡ 71 CU FAST</span>
              </div>
            </div>
          </div>
          <div style="font-size:13px;line-height:1.6;color:var(--mute)">10-step composite risk framework: Security 30% · Smart-Market 25% · Activity 25% · Volume 20%. A-F research grade + BUY / SELL verdict. Paste any Solana address.</div>
          <div style="display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:4px">
            <span class="pillr" style="padding:4px 10px;font-size:11px;background:var(--good-bg);border:1px solid var(--good);color:var(--good);border-radius:999px;font-weight:700">▶ Click → paste address → ▶ Run (71 CU)</span>
            <span style="font-weight:700;font-size:12px;color:var(--mute)">Skill #3</span>
          </div>
        </div>
        <!-- Demo 3 · API Key Manager -->
        <div class="skillCard demoCard" data-cat="utils-settings" data-idx="${CATALOG.findIndex(g=>catIdOf(g)==='utils-settings')}" data-skill="key" data-act="detail" style="padding:22px;gap:14px;min-height:auto;cursor:pointer">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:30px">🔑</span>
            <div style="display:flex;flex-direction:column;gap:4px;min-width:0">
              <h3 style="margin:0;font-size:16px;font-weight:800">API Key Manager</h3>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <span class="tag live" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">LIVE</span>
                <span class="tag birdeye" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700">🛰 Birdeye Data</span>
                <span class="tag" style="padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600">⚡ 0 CU</span>
              </div>
            </div>
          </div>
          <div style="font-size:13px;line-height:1.6;color:var(--mute)">Two tabs: 🛰 Birdeye (paste API key → session/RAM or persist ~/.birdeye.env) + 🤖 AI BYO (OpenAI/Anthropic/OpenRouter/Gemini per-provider Apply/Save/Clear). Masked 16• dots, localStorage never raw.</div>
          <div style="display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:4px">
            <span class="pillr" style="padding:4px 10px;font-size:11px;background:var(--tag);border:1px solid var(--line);border-radius:999px;font-weight:700">⚙ 2 tabs · Birdeye + AI BYO · 0 CU cost</span>
            <span style="font-weight:700;font-size:12px;color:var(--mute)">Skill #28</span>
          </div>
        </div>
      </div>
    </section>`;
  }

  // ============ D · SKILLS HUB (unfiltered + filtered) ============
  const secD = `
  <section style="padding:24px 0">
    <div class="homeSecHead" style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <h2 style="font-size:18px;font-weight:700;margin:0">🏪 Skills Hub</h2>
      <div style="flex:1"></div>
      <span class="subtle" style="font-size:12px">Click filter → view cards → Run / Detail</span>
    </div>
    ${fbar}
    <div class="homeTopBar" style="padding:10px 0 4px">
      <h2 style="margin:0;padding:0;font-size:18px;font-weight:700">${(f==='all')
        ? `🛰 All 32 Birdeye Data Skills · 🟢 ${liveTotal} LIVE`
        : `${catIcon(gFound||{cat:''})} ${htmlEscape(catTitle(gFound||{cat:f}))} · ${gFound? catCount(gFound):0} skills`}</h2>
      <div style="flex:1"></div>
    </div>
    <p class="hero" style="margin:0 0 14px">${heroText}</p>
    ${bodyHtml}
  </section>`;

  const html = `
  <div class="homeWrap" style="padding:0 6px;max-width:1400px;margin:0 auto">
    ${secA}${secB}${secC}${secD}
  </div>`;
  $('homeView').innerHTML = html;

  // ===== Wire HOME section buttons (A/B/C, only when f==='all') =====
  if(f === 'all'){
    // Theme logo swap (dark/light images preloaded)
    (function(){
      var theme = (document.documentElement.getAttribute('data-theme')||'dark');
      var logo = $('homeLogo');
      if(logo){ logo.src = theme==='dark' ? '/assets/birdeye-logo-official-dark.png' : '/assets/birdeye-logo-official-light.png'; }
    })();
    // B copy command (CLI Install card)
    var doCopy = function(){
      try{
        var txt = $('homeCmd')?.innerText || '';
        navigator.clipboard?.writeText(txt);
        var m = $('homeCopyMsg'); if(m){ m.textContent = '✅ Copied 3 lines to clipboard.'; setTimeout(function(){ if(m) m.textContent='⬆ click box to copy to clipboard'; }, 2500); }
      }catch(e){}
    };
    $('homeCmd') && ($('homeCmd').onclick = doCopy);
    $('homeCopyBtn') && ($('homeCopyBtn').onclick = doCopy);
  }

  // Wire ALL skill-level cards → entire card clickable (showcase C, Live Demos C, AND Skills Hub D)
  // Inside each card: <a>/<button>/<input> clicks still bubble-stop via stopPropagation so they work standalone
  $('homeView').querySelectorAll('.skillCard[data-skill]').forEach(card=>{
    const catId = card.dataset.cat;
    const skillId = card.dataset.skill;
    if(!catId || !skillId) return;
    const btn = card.querySelector('.sDetail');
    const handler = (ev)=>{
      const t = ev.target;
      if(t.closest('button') || t.closest('a') || t.closest('input') || t.closest('pre') || t.closest('[data-skip-card-click]')) return;
      ev.preventDefault();
      try {
        localStorage.setItem('be.sk.views.'+skillId, String((parseInt(localStorage.getItem('be.sk.views.'+skillId)||'0',10)||0)+1));
      } catch(e){}
      window.location.href = buildDetailUrl(skillId, catId);
    };
    card.style.cursor = card.style.cursor || 'pointer';
    card.onclick = handler;
    if(btn){
      btn.onclick = (ev)=>{
        ev.preventDefault();
        ev.stopPropagation();
        try {
          localStorage.setItem('be.sk.views.'+skillId, String((parseInt(localStorage.getItem('be.sk.views.'+skillId)||'0',10)||0)+1));
        } catch(e){}
        window.location.href = buildDetailUrl(skillId, catId);
      };
    }
  });
}

// ================== DRILL view (sidebar + ctrl + out) ==================
function goHome(){
  window.location.href = buildHomeUrl(window.STATE.homeFilter || 'all');
}

function drillMode(catId, idx){
  if(APP_PAGE !== 'detail'){
    const fallbackSkill = window.STATE.skill || ((idx!=null && CATALOG[idx] && (CATALOG[idx].items||[])[0] && CATALOG[idx].items[0].id) || '');
    window.location.href = buildDetailUrl(fallbackSkill, catId);
    return;
  }
  // find catalog index by id
  window.STATE.mode = 'drill';
  window.STATE.activeCategory = catId;
  // default expand this cat, collapse others (only once, not overwriting user clicks later)
  CATALOG.forEach((g,i)=>{
    const id = catIdOf(g);
    if(window.STATE.collapsed[id] === undefined){
      window.STATE.collapsed[id] = (id !== catId);
    }
  });
  // Force current cat expanded
  window.STATE.collapsed[catId] = false;
  // If catalog idx passed and no skill chosen yet → auto-select first LIVE skill in cat if any for convenience (but NOT auto-run)
  if(window.STATE.skill == null && idx!=null && CATALOG[idx]){
    const live = CATALOG[idx].items.find(x=>x.status==='live');
    const any = CATALOG[idx].items[0];
    window.STATE.skill = (live || any || {}).id || null;
  }
  // Show/hide layouts
  $('homeView').style.display = 'none';
  $('drillView').style.display = '';
  // Banner adjustments
  $('goHubBtn').style.display = '';
  const bc = $('breadcrumb'); bc.style.display='';
  const gInfo = CATALOG[idx] || CATALOG.find(g=>catIdOf(g)===catId) || null;
  const curSkillObj = (gInfo && window.STATE.skill) ? (gInfo.items.find(x=>x.id===window.STATE.skill)||null) : null;
  const gTitle = gInfo? catTitle(gInfo):catId;
  const gIcon = catIcon(gInfo||{cat:''});
  bc.innerHTML = `<span class="bcSeg" onclick="window.location.href='${buildHomeUrl('all')}'" title="Back to Hub All categories">🏠 Hub</span> <span class="sep">/</span> <span class="bcSeg" onclick="window.location.href='${buildHomeUrl(catId)}'" title="Back to group skill cards"><b>${gIcon} ${htmlEscape(gTitle)}</b></span> ${curSkillObj?`<span class="sep">/</span> ${htmlEscape(curSkillObj.title)}`:''}`;
  // Render everything
  renderCatalog();
  renderSkillCtrl();
  refreshHistory();
}

function toggleGroup(catId){
  window.STATE.collapsed[catId] = !window.STATE.collapsed[catId];
  renderCatalog();
}

function renderCatalog(){
  const root = $('catalog'); if(!root) return;
  let html = '';
  CATALOG.forEach((g,idx)=>{
    const id = catIdOf(g);
    const title = catTitle(g);
    const n = catCount(g);
    const collapsed = !!window.STATE.collapsed[id];
    const isActiveCat = window.STATE.activeCategory === id;
    html += `<div class="group ${collapsed?'collapsed':''} ${isActiveCat?'active':''}">
      <div class="groupHead" data-cat="${id}" title="Click to ${collapsed?'expand':'collapse'}">
        <span class="caret">${collapsed?'▶':'▼'}</span>
        <span class="title">${catIcon(g)} ${htmlEscape(title)}</span>
        <span class="nBadge">${n}</span>
      </div>`;
    for(const it of g.items){
      const activeClass = (it.id===window.STATE.skill)? 'active':'';
      html += `<div class="item ${activeClass}" data-skill='${it.id}' data-cat="${id}"><div style="flex:1">${it.title}</div><div class="tag ${it.status}">${it.status==='live'?'LIVE':'WIP'} · ${it.cu}</div></div>`;
    }
    html += `</div>`;
  });
  root.innerHTML = html;
  // Wire group head clicks (toggle collapse)
  root.querySelectorAll('.groupHead').forEach(h=>{
    h.addEventListener('click', (ev)=>{ ev.stopPropagation(); toggleGroup(h.dataset.cat); });
  });
  // Wire skill item clicks (choose skill + enter drill mode if not yet)
  root.querySelectorAll('[data-skill]').forEach(el=>{
    el.onclick=(ev)=>{
      ev.stopPropagation();
      window.STATE.skill = el.dataset.skill;
      const catId = el.dataset.cat;
      if(catId) window.STATE.activeCategory = catId;
      // Update breadcrumb immediately (clickable bcSeg segments)
      const g = CATALOG.find(x=>catIdOf(x)===catId) || null;
      const it = (g && g.items.find(x=>x.id===window.STATE.skill)) || null;
      const gT = g? catTitle(g):catId;
      const gI = catIcon(g||{cat:''});
      const bc = $('breadcrumb');
      if(bc){
        bc.style.display='';
        bc.innerHTML = `<span class="bcSeg" onclick="window.location.href='${buildHomeUrl('all')}'" title="Back to Hub All categories">🏠 Hub</span> <span class="sep">/</span> <span class="bcSeg" onclick="window.location.href='${buildHomeUrl(catId)}'" title="Back to group skill cards"><b>${gI} ${htmlEscape(gT)}</b></span> ${it?`<span class="sep">/</span> ${htmlEscape(it.title)}`:''}`;
      }
      const url = new URL(window.location.href);
      url.searchParams.set('skill', window.STATE.skill);
      if(catId) url.searchParams.set('cat', catId);
      window.history.replaceState({}, '', url.toString());
      renderCatalog();
      renderSkillCtrl();
    };
  });
}

function htmlEscape(s){ return String(s).replace(/[&<>]/g, c=> ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function _scoreTooltipHTML(k){
  // k = 'SEC' | 'SMKT' | 'ACT' | 'VOL' | 'FINAL'
  if(k==='SEC'){
    return `<div class="sttTip">
      <h4>SEC · Security Risk (30%)</h4>
      <div style="font-size:11px;color:var(--mute);margin-bottom:4px">Base = 5/10. Adjustments from API /defi/token_security (30 CU).</div>
      <div class="sttRow"><span>Dev hold &lt; 2%</span><b>+3</b></div>
      <div class="sttRow"><span>Dev hold 2–5%</span><b>+2</b></div>
      <div class="sttRow"><span>Dev hold 5–10%</span><b>+1</b></div>
      <div class="sttRow"><span>Dev hold &gt; 10%</span><b>−2</b></div>
      <div class="sttRow"><span>Top10 hold &lt; 20%</span><b>+2</b></div>
      <div class="sttRow"><span>Top10 hold 20–40%</span><b>+1</b></div>
      <div class="sttRow"><span>Top10 hold &gt; 40%</span><b>−2</b></div>
      <div class="sttRow"><span>Honeypot = YES</span><b>=0 🔴</b></div>
      <div class="sttRow"><span>LP locked = YES</span><b>+1</b></div>
      <div style="margin-top:5px;font-size:11px;color:var(--mute)">Clamp [0–10]. Weight in FINAL = 30%.</div>
    </div>`;
  }
  if(k==='SMKT'){
    return `<div class="sttTip">
      <h4>SMKT · Smart Market Fit (25%)</h4>
      <div style="font-size:11px;color:var(--mute);margin-bottom:4px">Base = 5/10. Source: /smart-money/v1/token/list join (20 CU / 20-token batch).</div>
      <div class="sttRow"><span>Rank Top 100 ≤ #10</span><b>+4 🌟🌟🌟</b></div>
      <div class="sttRow"><span>Rank Top 100 ≤ #30</span><b>+3 🌟🌟</b></div>
      <div class="sttRow"><span>Rank Top 100 ≤ #60</span><b>+2 🌟</b></div>
      <div class="sttRow"><span>Rank Top 100 ≤ #100</span><b>+1</b></div>
      <div class="sttRow"><span>Wallet hold ≥ 20 (no rank)</span><b>+2</b></div>
      <div style="margin-top:5px;font-size:11px;color:var(--mute)">Clamp [0–10]. Weight in FINAL = 25%.<br>Signals: SM wallets holding token = institutional smart-money entered early.</div>
    </div>`;
  }
  if(k==='ACT'){
    return `<div class="sttTip">
      <h4>ACT · Activity + Momentum (25%)</h4>
      <div style="font-size:11px;color:var(--mute);margin-bottom:4px">Base = 5/10. Source: token_overview money_flow + price_changes (18 CU).</div>
      <div class="sttRow"><span>Buy ratio last ≥ 62%</span><b>+3</b></div>
      <div class="sttRow"><span>Buy ratio last ≥ 55%</span><b>+2</b></div>
      <div class="sttRow"><span>Buy ratio last ≥ 51%</span><b>+1</b></div>
      <div class="sttRow"><span>Buy ratio last ≤ 45%</span><b>−2</b></div>
      <div class="sttRow"><span>Buy ratio last ≤ 38%</span><b>−3</b></div>
      <div class="sttRow"><span>SM wallets ≥ 30</span><b>+3</b></div>
      <div class="sttRow"><span>SM wallets 10–29</span><b>+2</b></div>
      <div class="sttRow"><span>SM wallets 3–9</span><b>+1</b></div>
      <div class="sttRow"><span>Δ% (4h − 5m) &gt; +30</span><b>+1</b></div>
      <div class="sttRow"><span>Δ% (4h − 5m) &lt; −30</span><b>−1</b></div>
      <div style="margin-top:5px;font-size:11px;color:var(--mute)">Clamp [0–10]. Weight = 25%.</div>
    </div>`;
  }
  if(k==='VOL'){
    return `<div class="sttTip">
      <h4>VOL · Volume Trend (20%)</h4>
      <div style="font-size:11px;color:var(--mute);margin-bottom:4px">Base = 5/10. Source: buy_sell_rows Vol$ across windows 5m→24h.</div>
      <div class="sttRow"><span>Each window with Vol$ increase</span><b>+1 / window</b></div>
      <div class="sttRow"><span>0 windows with Vol$ increase</span><b>−2</b></div>
      <div style="margin-top:5px;font-size:11px;color:var(--mute)">Max bonus = # of windows − 1 (5m/15m/30m/1h/2h/4h/8h/24h). Clamp [0–10]. Weight = 20%.</div>
    </div>`;
  }
  if(k==='FINAL'){
    return `<div class="sttTip">
      <h4>⭐ FINAL · Weighted Score</h4>
      <div class="sttRow"><span>SEC · 30%</span><b>× 0.30</b></div>
      <div class="sttRow"><span>SMKT · 25%</span><b>× 0.25</b></div>
      <div class="sttRow"><span>ACT · 25%</span><b>× 0.25</b></div>
      <div class="sttRow"><span>VOL · 20%</span><b>× 0.20</b></div>
      <div style="height:1px;background:var(--line);margin:6px 0"></div>
      <div class="sttRow"><b style="color:var(--accent)">≥ 7.5</b><span>→ STRONG BUY</span></div>
      <div class="sttRow"><b style="color:var(--good)">6.2 – 7.4</b><span>→ BUY</span></div>
      <div class="sttRow"><b style="color:var(--warn)">5.0 – 6.1</b><span>→ HOLD / WATCH</span></div>
      <div class="sttRow"><b style="color:var(--warn)">3.5 – 4.9</b><span>→ AVOID</span></div>
      <div class="sttRow"><b style="color:var(--bad)">&lt; 3.5</b><span>→ SELL / RED FLAG</span></div>
      <div style="margin-top:5px;font-size:11px;color:var(--mute)">Formula = SEC·0.30 + SMKT·0.25 + ACT·0.25 + VOL·0.20. Clamp [0–10].</div>
    </div>`;
  }
  return '';
}

function _scoreCellHTML(k,n,final){
  const v = Number(n||0).toFixed(1);
  return `<div class="cell ${final?'final':''}"><b>${v}/10</b><span>${k}</span>${_scoreTooltipHTML(k)}</div>`;
}
function fmtUsd(v){
  if(v===null||v===undefined||v==='') return 'N/A';
  const n = Number(v); if(!isFinite(n)) return String(v);
  const abs=Math.abs(n);
  if(abs>=1e9) return (n/1e9).toFixed(1)+'B';
  if(abs>=1e6) return (n/1e6).toFixed(1)+'M';
  if(abs>=1e3) return (n/1e3).toFixed(1)+'K';
  if(abs>=1) return n.toFixed(2);
  return n.toPrecision(3);
}
function fmtPctSigned(v){
  if(v===null||v===undefined||Number.isNaN(Number(v))) return 'N/A';
  const n=Number(v); return (n>=0?'+':'') + n.toFixed(1) + '%';
}
function add$Label(v){ if(v===null||v===undefined||String(v).trim()===''||String(v)==='N/A') return 'N/A'; const s = fmtUsd(v); return (Number(v)<0?'-':'') + '$' + s.replace('-',''); }
function addrCut(a,h=6,t=4){ if(!a) return ''; if(a.length<=h+t+3) return a; return a.slice(0,h)+'…'+a.slice(-t); }

// ---------- Skill control panels ----------
const SKILL_CTRLS = {
  tl: ()=>`
    <h3>🔥 Skill #1 · Trending List</h3>
    <div class="subtle" style="font-size:12px">Top trending tokens by 24h volume.</div>
    <div class="row" style="margin-top:10px"><label>Chain</label>
      <select id="tl_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
    <div style="margin-top:6px;padding:8px 10px;border:1px dashed var(--line);border-radius:8px;background:var(--ctrl-bg);font-size:11.5px;color:var(--mute);line-height:1.6">
      <b>Call recipe:</b> 24h · v3-list · volumeUSD desc · limit 50.
    </div>
    <button class="run" id="tl_run" style="margin-top:14px">▶ Run</button>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
      <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
      <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
      <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
      <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
      <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
    </div>
  `,
  tl_v3: ()=>`
    <h3>🔥 Skill #1b · V3 Token List</h3>
    <div class="subtle" style="font-size:12px">V3 token list with trades + holders, min $1k volume.</div>
    <div class="row" style="margin-top:10px"><label>Chain</label>
      <select id="tl_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
    <div style="margin-top:6px;padding:8px 10px;border:1px dashed var(--line);border-radius:8px;background:var(--ctrl-bg);font-size:11.5px;color:var(--mute);line-height:1.6">
      <b>Call recipe:</b> 24h · volumeUSD desc · limit 50.
    </div>
    <button class="run" id="tl_run" style="margin-top:14px">▶ Run</button>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
      <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
      <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
      <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
      <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
      <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
    </div>
  `,
  dd: ()=>`
    <h3>🛡 Skill #3 · Token DD (Basic)</h3>
    <div class="subtle" style="font-size:12px">10-step risk, security & smart-money verdict. Use RugCheck Audit for full holder table.</div>
    <div class="row" style="margin-top:10px"><label>Chain</label>
      <select id="dd_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
    <div class="row"><label>Address</label>
      <input id="dd_address" type="text" placeholder="DaZG1BGU7ZRfoSAy3vWAtMmcMc2sdxcyZuAamxmLjH4"></div>
    <button class="run" id="dd_run" style="margin-top:14px">▶ Run</button>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
      <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
      <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
      <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
      <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
      <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
    </div>
    <div class="kv"><span>Selected</span><span id="dd_recent" class="subtle">—</span></div>
  `,
  rugcheck_risk_audit: ()=>`
    <h3>🔍 Skill #17b · RugCheck Audit (Live)</h3>
    <div class="subtle" style="font-size:12px">Rugcheck.xyz layout: holders, liquidity drawdown, security cohorts.</div>
    <div class="row" style="margin-top:10px"><label>Chain</label>
      <select id="rca_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
    <div class="row"><label>Address</label>
      <input id="rca_address" type="text" placeholder="BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK"></div>
    <div style="margin-top:6px;padding:8px 10px;border:1px dashed var(--line);border-radius:8px;background:var(--ctrl-bg);font-size:11.5px;color:var(--mute);line-height:1.6">
      <b>Call recipe:</b> Top 20 holders · 24h liquidity · insider auto-tagged.
    </div>
    <button class="run" id="rca_run" style="margin-top:14px">▶ Run</button>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
      <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
      <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
      <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
      <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
      <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
    </div>
    <div class="kv"><span>Selected</span><span id="rca_recent" class="subtle">—</span></div>
  `,
  key: ()=>`
    <details class="apiCollapse" style="border:1px solid var(--line);border-radius:10px;background:var(--panel)" data-open-label="Click to expand" data-close-label="Click to hide">
      <summary style="list-style:none;cursor:pointer;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:10px">
        <span><b>🔑 Skill #28 · API Keys</b><span class="subtle" style="font-size:11px;margin-left:8px">Hidden by default</span></span>
        <span class="subtle" style="font-size:11px">Click to expand</span>
      </summary>
      <div style="padding:2px 12px 12px">
        <div class="subtle" style="font-size:12px">Session = in-process RAM. Save = append ~/.birdeye.env permanently. Raw key never localStorage/disk.</div>
        <div id="kTabBar" style="display:flex;gap:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-top:10px">
          <button class="kTab on" data-ktab="be" style="flex:1;padding:8px;font-size:12px;font-weight:600;background:var(--grad-a);border:none;color:#fff;cursor:pointer">🛰 Birdeye</button>
          <button class="kTab" data-ktab="ai" style="flex:1;padding:8px;font-size:12px;font-weight:600;background:transparent;border:none;border-left:1px solid var(--line);color:var(--mute);cursor:pointer">🤖 AI BYO</button>
        </div>
        <div id="kTabPane_be" style="margin-top:10px">
          <div class="row"><label>Status</label><div id="keyStatus" class="subtle">…</div></div>
          <div style="display:flex;gap:6px;align-items:stretch;margin-top:6px">
            <input id="pasteKey2" type="password" placeholder="dc9909a243924571b64f7c65fa2c032f" style="flex:1;font-family:monospace;font-size:12px;padding:8px 10px;border-radius:8px;background:var(--input-bg);border:1px solid var(--line);color:var(--text);outline:none" />
            <button type="button" class="btn ghost keyEyeBtn" id="pasteKey2_eye" title="Show/hide key">👁</button>
          </div>
          <div class="copyrow" style="margin-top:8px">
            <button class="btn primary" data-act="apply" data-prov="birdeye">Apply session</button>
            <button class="btn" data-act="save" data-prov="birdeye">Save persist</button>
            <button class="btn ghost" data-act="clear" data-prov="birdeye">Clear</button>
          </div>
        </div>
        <div id="kTabPane_ai" style="display:none;margin-top:10px">
          <div class="section-title" style="margin:0 0 8px 0">AI Provider</div>
          <div class="segGroup" style="display:flex;gap:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;flex-wrap:wrap">
            <button id="aiP_openai" class="aiPBtn on" data-aip="openai" style="flex:1;padding:7px 6px;font-size:11px;font-weight:600;background:var(--grad-a);border:none;color:#fff;cursor:pointer">OpenAI</button>
            <button id="aiP_anthropic" class="aiPBtn" data-aip="anthropic" style="flex:1;padding:7px 6px;font-size:11px;font-weight:600;background:transparent;border:none;border-left:1px solid var(--line);color:var(--mute);cursor:pointer">Anthropic</button>
            <button id="aiP_openrouter" class="aiPBtn" data-aip="openrouter" style="flex:1;padding:7px 6px;font-size:11px;font-weight:600;background:transparent;border:none;border-left:1px solid var(--line);color:var(--mute);cursor:pointer">OpenRouter</button>
            <button id="aiP_gemini" class="aiPBtn" data-aip="gemini" style="flex:1;padding:7px 6px;font-size:11px;font-weight:600;background:transparent;border:none;border-left:1px solid var(--line);color:var(--mute);cursor:pointer">Gemini</button>
          </div>
          <div class="row" style="margin-top:10px"><label>Status</label><div id="aiKeyStatus" class="subtle">…</div></div>
          <div style="display:flex;gap:6px;align-items:stretch;margin-top:6px">
            <input id="ai_pasteKey" type="password" placeholder="sk-..." style="flex:1;font-family:monospace;font-size:12px;padding:8px 10px;border-radius:8px;background:var(--input-bg);border:1px solid var(--line);color:var(--text);outline:none" />
            <button type="button" class="btn ghost keyEyeBtn" id="ai_pasteKey_eye" title="Show/hide key">👁</button>
          </div>
          <div class="copyrow" style="margin-top:8px">
            <button class="btn primary" id="aiBtn_apply">Apply session</button>
            <button class="btn" id="aiBtn_save">Save persist</button>
            <button class="btn ghost" id="aiBtn_clear">Clear</button>
          </div>
          <div class="subtle" style="font-size:11px;margin-top:8px">💡 Keys kept in RAM only. Use 💬 chat (bottom-right) to ask your LLM to run skills.</div>
        </div>
      </div>
    </details>
  `,
  about: ()=>`
    <h3>ℹ Skill #30 · About</h3>
    <div class="subtle" style="font-size:12px">32-skills scaffold · stdlib HTTP · no npm/pip.</div>
    <div class="kv"><span>CLI</span><span class="pillr">${htmlEscape('birdeye-screener/scripts/birdeye_cli.py')}</span></div>
    <div class="kv"><span>Server</span><span class="pillr">${htmlEscape('birdeye_ui.py')}</span></div>
    <div class="kv"><span>Docs</span><a class="pillr" target="_blank" href="https://data.birdeye.so/docs/llms.txt">https://data.birdeye.so/docs/llms.txt ↗</a></div>
  `,
};
// ---- Junk Token Prediction (ML) ----
SKILL_CTRLS.junk_predict = ()=>`
  <h3>🔬 Skill #32 · Junk Token Prediction (ML)</h3>
  <div class="subtle" style="font-size:12px">Logistic-regression junk score (0–100) on 16 on-chain features. Score ≥ threshold → <b>JUNK</b>. Threshold auto-reads from <code>lr_params.json</code>.</div>
  <div class="row" style="margin-top:10px"><label>Chain</label>
    <select id="junk_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
  <div class="row"><label>Token addresses (1 per line or comma)</label>
    <textarea id="junk_tokens" rows="4" placeholder="DaZG1BGU7ZRfoSAy3vWAtMmcMc2sdxcyZuAamxmLjH4&#10;BFgvTe3pGQuAAGzZ28SVhPcHjBSh2BzPfsZWNtG7g8UK" style="font-family:monospace;font-size:11.5px;width:100%;box-sizing:border-box"></textarea></div>
  <button class="run" id="junk_run" style="margin-top:14px">▶ Run Junk Prediction</button>
  <button class="run" id="junk_quick_test" style="margin-top:8px;background:linear-gradient(90deg,#7c3aed,#2563eb)">⚡ Quick Test · 30 random tokens</button>
  <div style="margin-top:6px;padding:8px 10px;border:1px dashed var(--line);border-radius:8px;background:var(--ctrl-bg);font-size:11.5px;color:var(--mute);line-height:1.6">
    <b>Quick Test:</b> scrolls v3 token list → picks 30 random → scores each (300 CU). No address input needed.
  </div>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" data-side="junk" title="UI rendered cards">UI</button>
    <button class="bfmt" data-fmt="plain" data-side="junk" title="Plain ASCII text">Plain</button>
    <button class="bfmt" data-fmt="raw-json" data-side="junk" title="Raw JSON envelope">JSON</button>
  </div>
`;
// ---- Skill #6 · Spam Token Cleaner (stc) · Web scrape 0 holder CU ----
SKILL_CTRLS.stc = ()=>`
  <h3>🧹 Skill #6 · Spam Token Cleaner (stc)</h3>
  <div class="subtle" style="font-size:12px">High-MC dead tokens (MC ≥ $1B, V24h ≤ $50). Holder data from web scrape.</div>
  <div class="row" style="margin-top:10px"><label>Min Market Cap ($)</label>
    <input id="stc_min_mc" type="number" value="1000000000" min="1000000" step="1000000" style="font-family:monospace"></div>
  <div class="row"><label>Max Volume 24h ($)</label>
    <input id="stc_max_vol" type="number" value="50" min="0" step="10" style="font-family:monospace"></div>
  <div class="row"><label>Chains (comma, order matters)</label>
    <input id="stc_chains" type="text" value="solana" style="font-family:monospace;font-size:11.5px"></div>
  <div class="row"><label>Max tokens total (safe cap demo)</label>
    <input id="stc_max_tokens" type="number" value="5" min="1" max="500" style="font-family:monospace"></div>
  <div style="margin-top:6px;padding:8px 10px;border:1px dashed var(--line);border-radius:8px;background:var(--ctrl-bg);font-size:11.5px;color:var(--mute);line-height:1.6">
    <b>Run recipe:</b> Step1 V3-list sweep (sort=mc desc, cap=100/chain) → Step2 Web scrape holder top1/top10% 0 CU via puppeteer-core + Chrome → Step3 Identity batch top-wallets → Step4 sort by MC desc → TopWalletValue desc → Liq desc → V24h asc.
  </div>
  <button class="run" id="stc_run" style="margin-top:14px">▶ Run</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" data-side="stc" title="Rendered compact table for UI">UI</button>
    <button class="bfmt" data-fmt="plain" data-side="stc" title="Plain ASCII text (terminal)">Plain</button>
    <button class="bfmt" data-fmt="telegram" data-side="stc" title="Telegram markdown (triple backticks)">Telegram</button>
    <button class="bfmt" data-fmt="raw-json" data-side="stc" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
  </div>
`;

// ---- Skill #13 · Wallet Score · Best single-wallet mode 110 CU ----
SKILL_CTRLS.wallet_score = ()=>`
  <h3>🧠 Skill #13 · Wallet Score</h3>
  <div class="subtle" style="font-size:12px">4-component alpha score: Profitability ×35 · Consistency ×35 · Quality ×20 · Activity ×10. Deep-loss tokens (bag-hold only) penalize Quality.</div>
  <div class="row" style="margin-top:12px"><label>Chain</label>
    <select id="ws_chain">
      <option value="sol" selected>solana</option>
      <option value="bsc">bsc</option>
      <option value="base">base</option>
      <option value="eth">ethereum</option>
      <option value="arc">arbitrum</option>
      <option value="robinhood">robinhood</option>
    </select></div>
  <div class="row"><label>Wallet address</label>
    <input id="ws_address" type="text" value="" placeholder="Wallet addr (auto-select on click)" style="font-family:monospace;font-size:11.5px"></div>
  <div class="row"><label>PnL window (duration)</label>
    <select id="ws_duration">
      <option value="24h">24h</option>
      <option value="7d">7d</option>
      <option value="30d" selected>30d (default)</option>
      <option value="90d">90d</option>
      <option value="all">all</option>
    </select></div>
  <div class="row"><label>PnL method</label>
    <select id="ws_pnl_method">
      <option value="wac" selected>wac (weighted avg cost)</option>
      <option value="net_cash">net_cash (cashflow diff)</option>
    </select></div>
  <div class="row" style="margin-top:6px"><label style="font-size:11px;color:var(--mute)">CU optimizations (skip = save CU)</label>
    <div style="display:flex;flex-wrap:wrap;gap:6px 10px;font-size:11px;color:var(--mute)">
      <label style="display:flex;align-items:center;gap:3px"><input type="checkbox" id="ws_skip_rug"> skip /wallet/v2/pnl per-token rug% (-30 CU)</label>
      <label style="display:flex;align-items:center;gap:3px"><input type="checkbox" id="ws_skip_first_tx"> skip FirstTx provenance (-40 CU, wallet age N/A)</label>
      <label style="display:flex;align-items:center;gap:3px"><input type="checkbox" id="ws_skip_portfolio"> skip Portfolio V2 net-worth (-30 CU, NW from summary)</label>
      <label style="display:flex;align-items:center;gap:3px;color:#a78bfa"><input type="checkbox" id="ws_include_style"> + Wallet Style badge (0 extra CU, reuses data)</label>
    </div>
  </div>
  <button class="run" id="wallet_score_run" style="margin-top:14px">▶ Run</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
    <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
    <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
    <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
  </div>
  <details style="margin-top:8px;font-size:11.2px;line-height:1.55;color:var(--mute)">
    <summary style="cursor:pointer;font-weight:700;color:#7fb3ff">🧮 Formula (v3.1) — click to expand</summary>
    <div style="margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--ctrl-bg)">
    <div>• <b>Profitability</b> = base × keep_factor. Leaderboard top-100 → 85..100; below → 10..85 by realized/lb_min. keep_factor = max(0, 1 − |unr|/realized).</div>
    <div>• <b>Consistency</b> = 0.20×win_rate + 0.40×trend + 0.25×trade_dist + 0.15×confidence.</div>
    <div>• <b>Quality</b> = 0.35×realization + 0.35×(1−concentration) + 0.30×loss_discipline − rug_penalty.</div>
    <div>• <b>Activity</b> = (0.60×vol + 0.40×tx_confidence×100) × bot_penalty (floor 0.70 when tx>300).</div>
    <div>Sustainability gates: 30D≤0→cap 39 · 90D≤0→cap 49 · prev60D≤0 AND |prev60d|>$100→cap 69. Hard filters (tx/vol/rug) = informational only.</div>
    </div>
  </details>
`;

SKILL_CTRLS.wallet_style = ()=>`
  <h3>🎭 Skill #11 · Wallet Style</h3>
  <div class="subtle" style="font-size:12px">Classify a wallet by <b>frequency (L1–L4) × P&amp;L (P1–P5)</b> → 20-cell style grid + speed subtitle + trading badges. Reuses wallet-score's permanent first-funded cache for wallet age (no extra 40 CU).</div>
  <div class="row" style="margin-top:12px"><label>Chain</label>
    <select id="wst_chain">
      <option value="sol" selected>solana</option>
      <option value="bsc">bsc</option>
      <option value="base">base</option>
      <option value="eth">ethereum</option>
      <option value="arc">arbitrum</option>
    </select></div>
  <div class="row"><label>Wallet address</label>
    <input id="wst_address" type="text" value="" placeholder="Wallet addr (auto-select on click)" style="font-family:monospace;font-size:11.5px"></div>
  <div class="row"><label>P&amp;L window</label>
    <select id="wst_duration">
      <option value="7d">7d</option>
      <option value="30d" selected>30d (default)</option>
    </select></div>
  <div class="row"><label>PnL method</label>
    <select id="wst_pnl_method">
      <option value="wac" selected>wac (weighted avg cost)</option>
      <option value="net_cash">net_cash (cashflow diff)</option>
    </select></div>
  <div class="row" style="margin-top:6px"><label style="font-size:11px;color:var(--mute)">CU optimizations (skip = save CU)</label>
    <div style="display:flex;flex-wrap:wrap;gap:6px 10px;font-size:11px;color:var(--mute)">
      <label style="display:flex;align-items:center;gap:3px"><input type="checkbox" id="wst_skip_tx_list" checked> skip /v1/wallet/tx_list (-30 CU, no speed/badge timing)</label>
      <label style="display:flex;align-items:center;gap:3px"><input type="checkbox" id="wst_skip_first_tx"> skip FirstTx provenance (-40 CU, wallet age N/A)</label>
    </div>
  </div>
  <button class="run" id="wallet_style_run" style="margin-top:14px">▶ Run</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" title="UI rendered style card">UI</button>
    <button class="bfmt" data-fmt="plain"    title="Plain ASCII text">Plain</button>
    <button class="bfmt" data-fmt="telegram" title="Telegram markdown">Telegram</button>
    <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope">JSON</button>
  </div>
  <details style="margin-top:8px;font-size:11.2px;line-height:1.55;color:var(--mute)">
    <summary style="cursor:pointer;font-weight:700;color:#7fb3ff">🧮 Formula — click to expand</summary>
    <div style="margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--ctrl-bg)">
    <div>• <b>Frequency</b> = (buy + sell) / window_days → L1 (&lt;1/d), L2 (1–10/d), L3 (10–50/d), L4 (&gt;50/d).</div>
    <div>• <b>pnl_ratio</b> = realized_profit_usd / total_invested_usd.</div>
    <div>• <b>P&amp;L level</b> (test in order, stop at first): P5 → pnl_ratio&gt;0.5 AND token_num≥5 AND (WR≥0.5 OR losers&lt;15%); P4 → pnl_ratio&gt;0.1; P1 → losers≥40% AND realized&lt;0; P3 → |pnl_ratio|≤0.10; P2 → realized&lt;0 OR pnl_ratio&lt;0.</div>
    <div>• <b>Speed</b> = median copy window (first buy → first sell) from tx_list: &lt;60s flash, &lt;24h intraday, &lt;7d swing, ≥7d long hold.</div>
    <div>• <b>Badges</b> (orthogonal): lottery, scale-in/out, hoarding, distributing, whale, new wallet (&lt;30d), insufficient sample.</div>
    </div>
  </details>
`;

SKILL_CTRLS.kline_pattern = ()=>`
  <h3>🕯️ Skill #21 · Kline Pattern</h3>
  <div class="subtle" style="font-size:12px">6 numbers → 11 candlestick patterns → 0..100 score. One <code>/defi/v3/ohlcv</code> call (CU scales with candle count: 25–100).</div>
  <div class="row" style="margin-top:12px"><label>Chain</label>
    <select id="kp_chain">
      <option value="sol" selected>solana</option>
      <option value="bsc">bsc</option>
      <option value="base">base</option>
      <option value="eth">ethereum</option>
      <option value="arc">arbitrum</option>
      <option value="robinhood">robinhood</option>
    </select></div>
  <div class="row"><label>Token address</label>
    <input id="kp_address" type="text" value="" placeholder="Token contract address" style="font-family:monospace;font-size:11.5px"></div>
  <div class="row"><label>Resolution</label>
    <select id="kp_resolution">
      <option value="1m">1m</option>
      <option value="5m">5m</option>
      <option value="15m" selected>15m (default)</option>
      <option value="30m">30m</option>
      <option value="1h">1h</option>
      <option value="4h">4h</option>
      <option value="1d">1d</option>
    </select></div>
  <div class="row"><label>Lookback window</label>
    <select id="kp_window">
      <option value="1d">1d</option>
      <option value="3d">3d</option>
      <option value="7d" selected>7d (default)</option>
      <option value="14d">14d</option>
      <option value="30d">30d</option>
      <option value="90d">90d</option>
      <option value="365d">1y</option>
    </select></div>
  <button class="run" id="kline_pattern_run" style="margin-top:14px">▶ Run</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" title="UI rendered pattern card">UI</button>
    <button class="bfmt" data-fmt="plain"    title="Plain ASCII text">Plain</button>
    <button class="bfmt" data-fmt="telegram" title="Telegram markdown">Telegram</button>
    <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope">JSON</button>
  </div>
  <details style="margin-top:8px;font-size:11.2px;line-height:1.55;color:var(--mute)">
    <summary style="cursor:pointer;font-weight:700;color:#7fb3ff">🧮 Formula — click to expand</summary>
    <div style="margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--ctrl-bg)">
    <div>• <b>6 numbers</b>: trend_up (mean(C[-9:]) vs mean(C[-21:])), slope, volatility = mean((H-L)/C last 14), drawdown = (max(H)−C[-1])/max(H), vol_ratio = V[-1]/mean(V[-21:-1]), up_from_low = (C[-1]−min(L))/min(L).</div>
    <div>• <b>11 patterns</b> (first-match-wins): vertical run-up, uptrend channel, breakdown, bounce off lows, distribution at highs, slow bleed, basing at lows, wide chop, bullish/bearish/sideways consolidation.</div>
    <div>• <b>Score</b>: start 50, ± per pattern, then universal: drawdown&gt;50% −10, up_from_low&gt;100% −5, volatility&gt;20% −5, vol_ratio&lt;0.5 −5.</div>
    </div>
  </details>
`;

SKILL_CTRLS.trending_score = ()=>`
  <h3>📈 Skill #22 · Token Trending Score</h3>
  <div class="subtle" style="font-size:12px">0..100 momentum score across <b>1m / 5m / 1h / 4h / 24h</b>. 6 components: Volume 20% · Swap 15% · Price 20% · Liquidity 15% · Holder 15% · Security 15%. Security &lt;40 → hard cap 0.1× (scam-proof). ~206 CU. Raw data + snapshots → CSV for backtest/ML tuning.</div>
  <div class="row" style="margin-top:12px"><label>Chain</label>
    <select id="ts_chain">
      <option value="sol" selected>solana</option>
      <option value="bsc">bsc</option>
      <option value="base">base</option>
      <option value="eth">ethereum</option>
      <option value="arc">arbitrum</option>
      <option value="robinhood">robinhood</option>
    </select></div>
  <div class="row"><label>Token address</label>
    <input id="ts_address" type="text" value="" placeholder="Token contract address" style="font-family:monospace;font-size:11.5px"></div>
  <div class="row"><label>1m candles</label>
    <select id="ts_candles">
      <option value="1000">1000 (~17h · 40 CU)</option>
      <option value="3000">3000 (~50h · 75 CU)</option>
      <option value="5000" selected>5000 (~83h · 100 CU)</option>
    </select></div>
  <button class="run" id="trending_score_run" style="margin-top:14px">▶ Run</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" title="UI rendered scorecard">UI</button>
    <button class="bfmt" data-fmt="plain"    title="Plain ASCII text">Plain</button>
    <button class="bfmt" data-fmt="telegram" title="Telegram markdown">Telegram</button>
    <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope">JSON</button>
  </div>
  <details style="margin-top:8px;font-size:11.2px;line-height:1.55;color:var(--mute)">
    <summary style="cursor:pointer;font-weight:700;color:#7fb3ff">🧮 Formula — click to expand</summary>
    <div style="margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--ctrl-bg)">
    <div><b>Growth Score (Volume, Swaps, Wallets):</b> G=(cur+ε)/(baseline+ε) · score=min(100, 100·ln(1+G)/ln(16))</div>
    <div>• <b>Volume (20%)</b>: v{interval}USD growth vs baseline median (or *History* field)</div>
    <div>• <b>Swap (15%)</b>: trade{interval} growth vs baseline</div>
    <div>• <b>Price (20%)</b>: priceChange{interval}% → growth-style normalization</div>
    <div>• <b>Liquidity (15%)</b>: liq/mcap ratio (70%) + 1h stability (30%)</div>
    <div>• <b>Holder (15%)</b>: count sufficiency log 1M→100 (60%) + unique wallet growth (40%)</div>
    <div>• <b>Security (15%)</b>: start 100; honeypot→0; mint −30; freeze −25; LP unlocked −25; top10&gt;60% −20; sell tax&gt;10% −20</div>
    <div>• <b>Baseline</b>: median of collected snapshots (1m=last 1h, 5m=last 4h, 1h=last 24h, 4h=last 72h, 24h=last 7d). Falls back to Birdeye *History* field.</div>
    <div>• <b>Risk gate</b>: security &lt; 40 → final = raw × 0.1 (scam tokens can't trend)</div>
    <div>• <b>Data</b>: token_creation_info + OHLCV v3 from creation + liquidity 1m from creation + token_overview + token_security(cached 7d) → CSV</div>
    </div>
  </details>
`;

SKILL_CTRLS.contract_dd = ()=>`
  <h3>🛡️ Skill #5 · Contract DD</h3>
  <div class="subtle" style="font-size:12px">Composite 0..100 score from <b>contract safety (45%)</b> + <b>holder structure (30%)</b> + <b>price action (25%)</b>. ~86 CU (kline scales with candle count).</div>
  <div class="row" style="margin-top:12px"><label>Chain</label>
    <select id="cdd_chain">
      <option value="sol" selected>solana</option>
      <option value="bsc">bsc</option>
      <option value="base">base</option>
      <option value="eth">ethereum</option>
      <option value="arc">arbitrum</option>
      <option value="robinhood">robinhood</option>
    </select></div>
  <div class="row"><label>Token address</label>
    <input id="cdd_address" type="text" value="" placeholder="Token contract address" style="font-family:monospace;font-size:11.5px"></div>
  <div class="row" style="margin-top:6px"><label style="font-size:11px;color:var(--mute)">CU optimizations</label>
    <div style="display:flex;flex-wrap:wrap;gap:6px 10px;font-size:11px;color:var(--mute)">
      <label style="display:flex;align-items:center;gap:3px"><input type="checkbox" id="cdd_skip_kline"> skip kline price-action (-5 CU)</label>
    </div>
  </div>
  <button class="run" id="contract_dd_run" style="margin-top:14px">▶ Run</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
    <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
    <button class="bfmt on" data-fmt="render" title="UI rendered scorecard">UI</button>
    <button class="bfmt" data-fmt="plain"    title="Plain ASCII text">Plain</button>
    <button class="bfmt" data-fmt="telegram" title="Telegram markdown">Telegram</button>
    <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope">JSON</button>
  </div>
  <details style="margin-top:8px;font-size:11.2px;line-height:1.55;color:var(--mute)">
    <summary style="cursor:pointer;font-weight:700;color:#7fb3ff">🧮 Formula — click to expand</summary>
    <div style="margin-top:6px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--ctrl-bg)">
    <div>• <b>Safety (45%)</b>: start 100. mint active −25, freeze active −20, LP unlocked −25, buy/sell tax &gt;10% −15 each, &gt;5% −5 each, honeypot −50.</div>
    <div>• <b>Holders (30%)</b>: start 100. top10 &gt;70% −30, &gt;50% −15, &gt;30% −5; #1 &gt;30% −25, &gt;15% −10; holders &lt;100 −20, &lt;500 −5.</div>
    <div>• <b>Price (25%)</b>: kline-pattern score (vertical run-up +25, breakdown −25, etc.) starting at 50.</div>
    <div>• <b>Tier</b>: ≥75 Safe 🟢, ≥55 Caution 🟡, ≥35 Risky 🟠, else Danger 🔴.</div>
    </div>
  </details>
`;

SKILL_CTRLS.new_pair = SKILL_CTRLS.security = SKILL_CTRLS.chart =
SKILL_CTRLS.compare = SKILL_CTRLS.sm_tokens =
SKILL_CTRLS.wallet_portfolio = SKILL_CTRLS.wallet_money_flow =
SKILL_CTRLS.copy_trade = SKILL_CTRLS.rug_score =
SKILL_CTRLS.lp_check = SKILL_CTRLS.kols = SKILL_CTRLS.chains = SKILL_CTRLS.pf_tokens =
SKILL_CTRLS.meme_index = SKILL_CTRLS.price_1y = SKILL_CTRLS.vol_profile =
SKILL_CTRLS.corr_map = SKILL_CTRLS.events = SKILL_CTRLS.alert_surge = SKILL_CTRLS.tg_signal =
SKILL_CTRLS.billing = ()=>{
  // find skill info
  let info=null;
  for(const g of CATALOG){ for(const it of g.items){ if(it.id===window.STATE.skill){ info=it; break; } } }
  return `<h3>${htmlEscape(info? info.title:'Skill')}</h3>
    <div class="subtle" style="font-size:12px">${htmlEscape(info? info.desc:'')}</div>
    <div class="pillr warn" style="align-self:flex-start">🛠 WIP · Design doc ready — implementation coming soon.</div>
    <button class="btn ghost" id="readApiDocBtn" data-skill="${STATE.skill}">📖 Read design doc</button>`;
};

// ---- Skill #9 · Smart Traders — dynamic criteria control panel ----
SKILL_CTRLS.sm_wallets = ()=>{
  return `<h3>🧠 Skill #9 · Smart Money Profile</h3>
    <div class="subtle" style="font-size:12px">Single-wallet behavior analysis: performance trend, trading style, TP/SL patterns, copy-trade ROI estimate, 🟢/🟡/🔴 verdict.</div>
    <div class="row" style="margin-top:14px"><label>Chain</label>
      <select id="dd_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
    <div class="row"><label>Wallet</label>
      <input id="sm9_wallet" type="text" placeholder="paste wallet address" style="width:100%" /></div>
    <div class="row"><label>PnL method</label>
      <select id="sm9_pnl"><option value="wac">wac</option><option value="net_cash">net_cash</option></select></div>
    <div class="row"><label>Skips</label>
      <label class="subtle" style="font-size:11px"><input type="checkbox" id="sm9_skip_tx" /> skip tx-list</label>
      <label class="subtle" style="font-size:11px"><input type="checkbox" id="sm9_skip_first" /> skip first-funded</label></div>
    <button class="run" id="sm9_run" style="margin-top:14px">▶ Run Smart Money Profile</button>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
      <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
      <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
      <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
      <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
      <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
    </div>`;
};
// Wire Skill #9 control panel interactivity
function _wireSm9Panel(){
  if(window.STATE.skill !== 'sm_wallets') return;
  const $id = id => document.getElementById(id);
}

// ---- Skill #14 · Wallet Analysis — control panel ----
SKILL_CTRLS.sm_flow_token = ()=>{
  return `<h3>💰 Skill #14 · Wallet Analysis</h3>
    <div class="subtle" style="font-size:12px">Single-wallet deep-dive: profile, assets (current + intervals), trading & PnL by interval, risk metrics.</div>
    <div class="row" style="margin-top:14px"><label>Chain</label>
      <select id="wa_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option><option>arc</option><option>robinhood</option></select></div>
    <div class="row"><label>Wallet</label>
      <input id="wa_wallet" type="text" placeholder="paste wallet address" style="width:100%" /></div>
    <div class="row"><label>Horizon</label>
      <select id="wa_horizon"><option value="short">short</option><option value="normal" selected>normal</option><option value="long">long</option></select>
      <span class="subtle" style="font-size:10px">short=24h,7d,30d · normal=24h,7d,30d,90d · long=30d,90d,all</span></div>
    <div class="row"><label>PnL method</label>
      <select id="wa_pnl"><option value="wac">wac</option><option value="net_cash">net_cash</option></select></div>
    <div class="row"><label>Skips</label>
      <label class="subtle" style="font-size:11px"><input type="checkbox" id="wa_skip_tx" /> skip tx-list</label>
      <label class="subtle" style="font-size:11px"><input type="checkbox" id="wa_skip_first" /> skip first-funded</label>
      <label class="subtle" style="font-size:11px"><input type="checkbox" id="wa_skip_port" /> skip portfolio</label></div>
    <button class="run" id="wa_run" style="margin-top:14px">▶ Run Wallet Analysis</button>
    <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:10px">
      <span style="font-size:11px;color:var(--mute);align-self:center;margin-right:4px">Output:</span>
      <button class="bfmt on" data-fmt="render" title="UI rendered scorecard / layout">UI</button>
      <button class="bfmt" data-fmt="plain"    title="Plain ASCII text (terminal)">Plain</button>
      <button class="bfmt" data-fmt="telegram" title="Telegram markdown (triple backticks)">Telegram</button>
      <button class="bfmt" data-fmt="raw-json" title="Raw JSON envelope (agent / LLM consumption)">JSON</button>
    </div>`;
};

function selectedFmt(side){
  // side = 'tl' or 'dd'. Return render/plain/telegram/raw-json. Defaults render.
  const sel = document.querySelectorAll('#skillCtrl .bfmt.on');
  for(const b of sel){ return b.dataset.fmt || 'render'; }
  return 'render';
}

// ---------- Universal 3-section skill-detail footer (opponent copy flow: Install / Core Capabilities / Agent prompts) ----------
// Appended AFTER the skill-specific control panel in renderSkillCtrl().
// Data source: dictionary SKILL_META_BY_ID — one key per skill.id in CATALOG.
const SKILL_META_BY_ID = {
  tl: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode simple --interval 24h --format scorecard`,
    installPresets: [
      { label: "FAST · 30 CU · 24h window · Scorecard UI",          cu: 30,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode simple --interval 24h --format scorecard` },
      { label: "FAST · 30 CU · 1h window · Scorecard UI",           cu: 30,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode simple --interval 1h  --format scorecard` },
      { label: "FAST · 30 CU · 5m pump window · Telegram markdown", cu: 30,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode simple --interval 5m  --format telegram` },
      { label: "FAST · 30 CU · platform=pump.fun + plain ASCII",     cu: 30,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode simple --interval 1h  --platform pump.fun --limit 50 --format plain` },
      { label: "Compare Run · Cache replay (0 CU) · raw-json dump",  cu: 0,   cmd: `python3 birdeye-screener/scripts/birdeye_cli.py history-render --run-id <LAST_RUN_ID> --format raw-json` },
      { label: "Multi-chain BSC · FAST 30 CU · Scorecard",           cu: 30,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain bsc --mode simple --interval 4h  --format scorecard` }
    ],
    coreCaps: [
      "Scan highest-volume tokens on-chain over last 5m / 1h / 4h / 24h",
      "Show market cap, liquidity, volume, trade count, holder count, dev share",
      "Sort by MC / volume / trades / holders; filter by platform (pump.fun, raydium, moonshot...)",
      "Supports SOL / BSC / Base / ETH multi-chain queries"
    ],
    agentPrompts: [
      "Show the top trending tokens on SOL in the past 5 minutes",
      "Show the top trending tokens on SOL in the past 1 hour",
      "List pump.fun tokens with 24h volume > $1M sorted by holder growth",
      "Compare trending vs V3 reliable list for the same 1h window — rank diff per token"
    ],
    apiAgg: "/api/v1/trending/simple?chain={chain}&interval={interval}&limit={limit}"
  },
  tl_v3: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode v3 --min-volume 10000 --sort-by volumeUSD --interval 1h --format scorecard`,
    installPresets: [
      { label: "BASE · 50 CU · min $10k V · volumeUSD sort · Scorecard",       cu: 50,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode v3 --min-volume 10000 --sort-by volumeUSD --interval 1h --format scorecard` },
      { label: "+extra_fields · 62 CU · platform filter · Scorecard",          cu: 62,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode v3 --min-volume 10000 --sort-by volumeUSD --interval 1h --platform raydium,pump.fun --include extra_fields --format scorecard` },
      { label: "+security_shallow · 80 CU · FAST rug drop · Telegram",         cu: 80,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode v3 --min-volume 10000 --sort-by volumeUSD --include extra_fields,security_shallow --limit 30 --format telegram` },
      { label: "Hunt min $100k V · holders ≥ 200 · plain ASCII",               cu: 50,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode v3 --min-volume 100000 --sort-by holder_count --min-holders 200 --format plain` },
      { label: "Pipeline gap check · 50 CU · dump rows v_1h_usd < $1 flag",     cu: 50,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py trending-list --chain sol --mode v3 --min-volume 1000 --sort-by volumeUSD --format raw-json | jq '.rows[] | select(.pipeline_gap==true)'` },
      { label: "Batch V3 → RugCheck sweep top-20 (0 CU format ×152 each",      cu: 3040,cmd: `# wrap in bash loop: for ADDR in $(v3 top-20 --addr-only); do cli token-dd --address $ADDR --include list,advanced_security --format rugcheck; done` }
    ],
    coreCaps: [
      "Accurate V3 list with numeric range filters (min_volume / MC bands / trade intervals)",
      "Sort by volumeUSD descending — default for reliability over upstream trending",
      "Filter by platform, liquidity ≥ min, holders ≥ min, price Δ% range",
      "Includes numeric per-row: trades_1h, unique_wallets_24h, holder_count, liq_usd, v1h/v24h USD"
    ],
    agentPrompts: [
      "Show SOL V3 tokens with min $10k volume in 1h — sort by volumeUSD",
      "Only Raydium + pump.fun tokens, 24h price change between +10% and +200%, holder ≥ 200",
      "Compare V3 top 20 vs Mode-B trending — list tokens only present in one list",
      "Pull V3 SOL tokens min $100k 1h volume — then run Token DD for each top 5"
    ],
    apiAgg: "/api/v1/trending/v3?chain={chain}&min_volume={minV}&sort={sort}&limit={limit}"
  },
  dd: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR> --include list,advanced_security --format scorecard`,
    installPresets: [
      { label: "BASE FAST · 71 CU · Scorecard (no extras)",                        cu: 71,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR> --format scorecard` },
      { label: "STANDARD · 122 CU · +list(holder top-20 + advsec tags+DD%)",       cu: 122, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR> --include list,advanced_security --format scorecard` },
      { label: "DEEP · 152 CU · +list + advsec + risk30d(Đức) · Telegram",         cu: 152, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR> --include list,advanced_security,risk_history --history-points 30 --format telegram` },
      { label: "STANDARD · 122 CU · raw-json (agent consumption)",                  cu: 122, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR> --include list,advanced_security --format raw-json` },
      { label: "FAST · 71 CU · plain ASCII (terminal quick peek)",                  cu: 71,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain sol --address <TOKEN_ADDR> --format plain` },
      { label: "0 CU replay from cache → scorecard rerender",                       cu: 0,   cmd: `python3 birdeye-screener/scripts/birdeye_cli.py history-render --run-id <LAST_RUN_ID> --format scorecard` },
      { label: "Multi-chain Base · DEEP 152 CU · includes all 3 flags",             cu: 152, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py token-dd --chain base --address <0xADDR_EVM> --include list,advanced_security,risk_history --format scorecard` }
    ],
    coreCaps: [
      "SEC 30% · SMKT 25% · ACT 25% · VOL 20% weighted score → A…F / NG grade + BUY/SELL verdict",
      "Holder & trader 24h delta, liq curr/min/max + drawdown%, tag% hold (Sniper / Bundler / Smart / KOL / Dev)",
      "Interpolated USD holding per tag / per holder-row (pct × MC ÷ 100 — 0 CU client)",
      "Optional includes: list (top-20 holders, 30 CU), advanced_security (tags + DD% + bot proxy, 21 CU), risk_history 30d daily snapshots (30 CU, source Đức)"
    ],
    agentPrompts: [
      "Run Token Due Diligence on address <TOKEN_ADDR> on Solana",
      "Full deep DD on <ADDR>: include top-20 holders + tag cohorts + 30d risk history",
      "Compare DD score of these 3 tokens side-by-side: <A>, <B>, <C> — which one to buy?",
      "Flag any token where rug score > 5 OR top-10 holder% > 60% — show me red flags"
    ],
    apiAgg: "/api/v1/token/dd?chain={chain}&address={addr}&include=list,advanced_security"
  },
  rugcheck_risk_audit: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --rug-show-holders`,
    installPresets: [
      { label: "STANDARD · 142 CU · 24h liq DD · holders top20 YES default · 7card UI", cu: 142, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --rug-show-holders --rug-liq-window 24h --rug-holders-top-n 20` },
      { label: "FAST BUDGET · 112 CU · liq24h + NO holder table (just T10% agg)", cu: 112, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --no-rug-show-holders --rug-liq-window 24h` },
      { label: "4H LIQ WINDOW · 142 CU · holders YES default",                         cu: 142, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --rug-liq-window 4h` },
      { label: "1H PUMP DRAIN CHECK · 142 CU · 1h liq DD",                             cu: 142, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --rug-liq-window 1h` },
      { label: "Telegram shareable · 142 CU · rug layout in ```block",                  cu: 142, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --format telegram` },
      { label: "Open RugCheck.xyz side-by-side (0 CU)",                                 cu: 0,   cmd: `open https://rugcheck.xyz/tokens/<TOKEN_ADDR>` },
      { label: "Raw JSON agent parse + 7card risks + cohort pct (0 CU extra)",          cu: 142, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py rugcheck-audit --chain sol --address <TOKEN_ADDR> --format raw-json` }
    ],
    coreCaps: [
      "RugCheck-equivalent 7-card risk layout: Mint/Liq/Honeypot/DevHold/Top10Conc/TagCohort/BotWash",
      "13-field 1-line overview (address/symbol/price/MC/liq/holders/V24h/holderΔ/traderΔ/liqDD/rugScore/tier/mint/lock/honey/top10%)",
      "Tier map 0–10: LOW / CAUTION / ELEVATED / HIGH / VERY HIGH / RUG-NG",
      "Same payload bytes as Token DD (list + advanced_security) → 0 CU format-switch between rug and scorecard"
    ],
    agentPrompts: [
      "Run RugCheck-style risk audit on token address <TOKEN_ADDR> SOL",
      "Show rug score + 7 cards + warn if any card flagged CRIT red",
      "Batch rug-audit top-10 V3 tokens — highlight all with ELEVATED tier or worse",
      "Compare rug tier vs DD scorecard letter rating for <ADDR> — do they agree on risk?"
    ],
    apiAgg: "/api/v1/token/rugcheck?chain={chain}&address={addr}&include=list,advanced_security"
  },
  sm_wallets: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py smart-money-profile --chain sol --wallet <WALLET> --format rendered`,
    installPresets: [
      { label: "Smart Money Profile · ~90 CU · rendered UI",     cu: 90,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py smart-money-profile --chain sol --wallet <WALLET> --format rendered` },
      { label: "Smart Money Profile · plain text",               cu: 90,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py smart-money-profile --chain sol --wallet <WALLET> --format plain` },
      { label: "Smart Money Profile · telegram markdown",        cu: 90,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py smart-money-profile --chain sol --wallet <WALLET> --format telegram` },
      { label: "Skip tx-list · save 30 CU (no style/TP-SL)",     cu: 60,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py smart-money-profile --chain sol --wallet <WALLET> --skip-tx-list --format rendered` },
      { label: "Output raw-json envelope (agent consumption)",   cu: 90,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py smart-money-profile --chain sol --wallet <WALLET> --format raw-json` }
    ],
    coreCaps: [
      "7d vs 30d performance trend — win rate + realized PnL, improving / stable / declining",
      "Trading style inference (scalper / day / swing / holder) from tx round-trip hold times",
      "Take-profit % and stop-loss % from average winning/losing round trips",
      "Copy-trade ROI estimate — avg return per completed round-trip + count",
      "🟢/🟡/🔴 verdict ladder: edge stopped working, can't get fills, doesn't cut losses, etc."
    ],
    agentPrompts: [
      "Analyze wallet <WALLET> trading behavior — style, TP/SL, copy-trade ROI, and verdict",
      "Is this wallet copy-tradeable? Run Smart Money Profile on <WALLET> and summarize the verdict",
      "What's the take-profit and stop-loss behavior of wallet <WALLET>?"
    ],
    apiAgg: "/api/v1/smart/wallets?depth=fast&winrate=40&pnl=25&rank=20&dd=15&pass=70"
  },
  sm_flow_token: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --horizon normal --format rendered`,
    installPresets: [
      { label: "Wallet Analysis · normal · rendered UI",        cu: 180, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --horizon normal --format rendered` },
      { label: "Wallet Analysis · short · rendered UI",         cu: 120, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --horizon short --format rendered` },
      { label: "Wallet Analysis · long · rendered UI",          cu: 210, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --horizon long --format rendered` },
      { label: "Wallet Analysis · plain text",                  cu: 180, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --format plain` },
      { label: "Wallet Analysis · telegram markdown",           cu: 180, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --format telegram` },
      { label: "Skip tx-list · save ~60 CU",                    cu: 120, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --skip-tx-list --format rendered` },
      { label: "Output raw-json envelope (agent consumption)",  cu: 180, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-analysis --chain sol --wallet <WALLET> --format raw-json` }
    ],
    coreCaps: [
      "Single-wallet deep-dive: profile, assets (current + by interval), trading & PnL by interval",
      "Horizon presets: short / normal / long — each preset maps to a different interval mix",
      "Risk metrics: concentration, win rate, trade count, average PnL per trade",
      "Immutable data cached (creation date, age) — 0 CU on repeat for first-funded"
    ],
    agentPrompts: [
      "Deep-dive wallet <WALLET>: profile, assets, trading & PnL by interval, risk",
      "Show wallet <WALLET> PnL across 24h, 7d, 30d, 90d, all — which interval is strongest?",
      "Analyze wallet <WALLET> concentration and win rate risk metrics"
    ],
    apiAgg: "/api/v1/wallet/{wallet}/portfolio?chain={chain}"
  },
  wallet_score: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format rendered`,
    installPresets: [
      { label: "STANDARD · 190 CU (150 repeat) · 30d · rendered UI",              cu: 190, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format rendered` },
      { label: "FAST EARLY-FAIL · 90 CU · summary + 90D gate",                cu: 90,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --skip-rug --skip-first-tx --skip-portfolio --format rendered` },
      { label: "LOWER CU · 150 CU · skip first-funded",           cu: 150, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --skip-first-tx --format rendered` },
      { label: "Telegram shareable · 190 CU (150 repeat) · compact summary",   cu: 190, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format telegram` },
      { label: "Raw JSON envelope · 190 CU (150 repeat) · agent parse",        cu: 190, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format raw-json` },
      { label: "COMPACT API · include score · 90 CU (numeric only, no formulas)", cu: 90, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --include score` },
      { label: "COMPACT API · include pnl,tokens · 60 CU (rug + PnL)",          cu: 60, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --include pnl,tokens` },
      { label: "COMPACT API · include pnl only · 30 CU (minimal)",                cu: 30, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-score --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --include pnl` },
      { label: "0 CU replay from cache run_id",                               cu: 0,   cmd: `python3 birdeye-screener/scripts/birdeye_cli.py history-render --run-id <LAST_RUN_ID> --format render` }
    ],
    coreCaps: [
      "Score one wallet 0-100 with Profitability 35%, Consistency 35%, Quality 20%, Activity 10%",
      "Profitability = fixed ROI + absolute profit magnitude: clamp((min(roi_realized, roi_total)+5%)/35% ×100) — −5%→0, +30%→100; blended realized+total PNL (no leaderboard call)",
      "Copy-tradeability score (0-100): 0.22×entry + 0.22×profit/trade + 0.20×hold + 0.18×feasible + 0.18×edge — can a follower capture this wallet's edge?",
      "Fully granular penalties: unrealized loss linear (|unr|≥realized→0), deep-loss weighted (only bag-hold tokens penalized)",
      "Deep-loss source: POST /wallet/v2/pnl/details — tokens with total%≤−50%; tiers ≥90%/≥75%/≥50%; only realized≤0 (bag-hold) penalized, realized>0 (smart-exit) not penalized",
      "Hard filters (tx/vol/deep-loss) = informational only — no alpha ×0.50; deep-loss penalized inside Quality",
      "New profitable wallets (no prev60D history) get trend=85 — not penalized for lacking history",
      "First-funded (wallet age) permanently cached per wallet → repeat runs save 40 CU (150 vs 190)",
      "Compact API: --include <blocks> returns numeric-only JSON (no formulas); CU scales with includes (30 CU for pnl only, 90 for full score)",
      "Transparent formula blocks, sustainability gates, hard filters, and tier output in one UI",
      "Optional CU-saving skips for rug%, first-funded provenance, and current net worth"
    ],
    agentPrompts: [
      "Score this wallet over 30d and show the formula breakdown: <WALLET_ADDR>",
      "Run Wallet Score on Base for <WALLET_ADDR> and tell me whether it is Elite, Pro, Novice, or Risk",
      "Compare the same wallet with and without skip-first-tx so I can see the CU tradeoff",
      "Open the cached Wallet Score result again in Telegram format with 0 extra CU"
    ],
    apiAgg: "CLI wallet-score aggregate pipeline (/wallet/v2/pnl/summary + optional rug/first-funded/net-worth)"
  },
  wallet_style: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-style --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format rendered`,
    installPresets: [
      { label: "STANDARD · 90 CU (60 repeat) · 30d · rendered UI",               cu: 90, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-style --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format rendered` },
      { label: "FAST · 60 CU (60 repeat) · skip tx_list (no speed badge)",       cu: 60, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-style --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --skip-tx-list --format rendered` },
      { label: "MINIMAL · 30 CU · skip tx_list + first-funded",                  cu: 30, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-style --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --skip-tx-list --skip-first-tx --format rendered` },
      { label: "Telegram shareable · 90 CU (60 repeat)",                         cu: 90, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-style --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format telegram` },
      { label: "Raw JSON envelope · 90 CU (60 repeat) · agent parse",            cu: 90, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py wallet-style --chain sol --wallet <WALLET_ADDR> --duration 30d --pnl-method wac --format raw-json` },
      { label: "0 CU replay from cache run_id",                                  cu: 0,  cmd: `python3 birdeye-screener/scripts/birdeye_cli.py history-render --run-id <LAST_RUN_ID> --format render` }
    ],
    coreCaps: [
      "Classify a wallet's trading style via 4×5 grid: Frequency (L1–L4) × P&L level (P1–P5)",
      "Frequency = (buy+sell)/window_days → L1 <1/d, L2 1–10/d, L3 10–50/d, L4 >50/d",
      "pnl_ratio = realized_profit_usd / total_invested_usd (realized_profit_pnl equivalent)",
      "P&L level (test in order, stop at first): P5 (ratio>0.5 & tokens≥5 & (WR≥0.5 or losers<15%)) → P4 (ratio>0.1) → P1 (losers≥40% & realized<0) → P3 (|ratio|≤0.10) → P2 (realized<0 or ratio<0)",
      "Speed subtitle = median copy window (first buy → first sell) from tx_list: <60s flash, <24h intraday, <7d swing, ≥7d long hold",
      "Orthogonal badges: lottery, scale-in, scale-out, hoarding, distributing, whale, new wallet (<30d), insufficient sample",
      "First-funded (wallet age) permanently cached per wallet → repeat runs save 40 CU",
      "4 outputs: rendered HTML (UI), plain ASCII, Telegram markdown, raw JSON envelope"
    ],
    agentPrompts: [
      "What's this wallet's trading style? Run Wallet Style on <WALLET_ADDR>",
      "Classify <WALLET_ADDR> as sniper, swing, or holder using the frequency × P&L grid",
      "Show me the badges for <WALLET_ADDR> — is it a whale, a hoarder, or a scale-in trader?",
      "Re-open the cached Wallet Style result in Telegram format with 0 extra CU"
    ],
    apiAgg: "CLI wallet-style pipeline (/wallet/v2/pnl/summary + /wallet/v2/pnl/details + optional /v1/wallet/tx_list + first-funded cache)"
  },
  kline_pattern: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 15m --window 7d --format rendered`,
    installPresets: [
      { label: "15m · 7d · rendered UI · ~40 CU (672 candles)", cu: 40, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 15m --window 7d --format rendered` },
      { label: "1h · 30d · rendered UI · ~40 CU (720 candles)",  cu: 40, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 1h --window 30d --format rendered` },
      { label: "5m · 1d · rendered UI · ~30 CU (288 candles)",   cu: 30, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 5m --window 1d --format rendered` },
      { label: "1d · 1y · rendered UI · ~40 CU (365 candles)",   cu: 40, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 1d --window 365d --format rendered` },
      { label: "Telegram shareable · ~40 CU",                     cu: 40, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 15m --window 7d --format telegram` },
      { label: "Raw JSON envelope · ~40 CU · agent parse",        cu: 40, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py kline-pattern --chain sol --address <TOKEN_ADDR> --resolution 15m --window 7d --format raw-json` }
    ],
    coreCaps: [
      "Classify candlestick pattern + 0..100 score",
      "6 core numbers: trend_up (up/down/flat), slope, volatility, drawdown, vol_ratio, up_from_low",
      "11 patterns (first-match-wins): vertical run-up, uptrend channel, breakdown, bounce off lows, distribution at highs, slow bleed, basing at lows, wide chop, bullish/bearish/sideways consolidation",
      "Score starts at 50 with +/- rules per pattern + universal adjustments (deep drawdown, far from lows, high volatility, volume drying up)",
      "1 Birdeye call: /defi/v3/ohlcv — CU scales with candle count (0–100→25, 101–300→30, 301–1000→40, 1001–2000→75, 2001–5000→100)"
    ],
    agentPrompts: [
      "What's the current kline pattern for <TOKEN_ADDR>? Run Kline Pattern on it",
      "Is <TOKEN_ADDR> in a vertical run-up, distribution, or breakdown? Use 15m 7d",
      "Scan <TOKEN_ADDR> on 1h 30d — is it basing at lows or slowly bleeding?"
    ],
    apiAgg: "CLI kline-pattern pipeline (/defi/v3/ohlcv → pattern + score)"
  },
  contract_dd: {
    installPrompt: `python3 birdeye-screener/scripts/birdeye_cli.py contract-dd --chain sol --address <TOKEN_ADDR> --format rendered`,
    installPresets: [
      { label: "STANDARD · ~86 CU · rendered UI",          cu: 86, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py contract-dd --chain sol --address <TOKEN_ADDR> --format rendered` },
      { label: "NO PRICE · ~61 CU · skip kline",          cu: 61, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py contract-dd --chain sol --address <TOKEN_ADDR> --skip-kline --format rendered` },
      { label: "Telegram shareable · ~86 CU",              cu: 86, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py contract-dd --chain sol --address <TOKEN_ADDR> --format telegram` },
      { label: "Raw JSON envelope · ~86 CU · agent parse", cu: 86, cmd: `python3 birdeye-screener/scripts/birdeye_cli.py contract-dd --chain sol --address <TOKEN_ADDR> --format raw-json` }
    ],
    coreCaps: [
      "Composite 0-100 score: contract safety 45% + holder structure 30% + price action 25%",
      "Safety: mint/freeze authority, LP lock %, buy/sell tax, honeypot check",
      "Holders: top-10 concentration, #1 holder, total holder count",
      "Price: kline-pattern score (reuses kline_pattern module)",
      "Tier: ≥75 Safe 🟢, ≥55 Caution 🟡, ≥35 Risky 🟠, else Danger 🔴",
      "4 Birdeye calls: token_overview (21) + token_security (30) + holder distribution (30) + ohlcv (25)"
    ],
    agentPrompts: [
      "Run Contract DD on <TOKEN_ADDR> — is it safe to buy?",
      "Check the contract safety + holder concentration for <TOKEN_ADDR>",
      "Give me the composite risk score for <TOKEN_ADDR> with all 3 pillars"
    ],
    apiAgg: "CLI contract-dd pipeline (token_overview + token_security + holder distribution + ohlcv → composite score)"
  },
  stc: {
    installPrompt: `python3 birdeye-screener/scripts/stc.py --min-mc 1000000000 --max-vol 50 --chains solana,robinhood,base,bsc,ethereum --format rendered`,
    installPresets: [
      { label: "ALL CHAINS · MC ≥ $1B · V24h ≤ $50 · rendered UI payload",           cu: 0, cmd: `python3 birdeye-screener/scripts/stc.py --min-mc 1000000000 --max-vol 50 --chains solana,robinhood,base,bsc,ethereum --format rendered` },
      { label: "SOL ONLY · MC ≥ $1B · V24h ≤ $50 · plain terminal",                   cu: 0, cmd: `python3 birdeye-screener/scripts/stc.py --min-mc 1000000000 --max-vol 50 --chains solana --format plain` },
      { label: "ETH+BASE+BSC · MC ≥ $1B · V24h ≤ $50 · telegram block",              cu: 0, cmd: `python3 birdeye-screener/scripts/stc.py --min-mc 1000000000 --max-vol 50 --chains ethereum,base,bsc --format telegram` },
      { label: "ROBINHOOD sweep · MC ≥ $1B · V24h ≤ $50 · raw-json agent pipe",      cu: 0, cmd: `python3 birdeye-screener/scripts/stc.py --min-mc 1000000000 --max-vol 50 --chains robinhood --format raw-json` },
      { label: "LOOSER · MC ≥ $500M · V24h ≤ $500 · plain quick scan",               cu: 0, cmd: `python3 birdeye-screener/scripts/stc.py --min-mc 500000000 --max-vol 500 --chains solana --format plain --nocache` },
      { label: "0 CU replay from cache prefix · pass --run-id <STORED_RUN_ID>",       cu: 0, cmd: `python3 birdeye-screener/scripts/stc.py --run-id stc_mc1000M_v50_<TS> --format rendered` }
    ],
    coreCaps: [
      "Step 1 V3 list sweep: sort_by=market_cap desc, min_market_cap=$1B server filter, 100 tokens/page, chains solana→robinhood→base→bsc→eth",
      "Client filter volume_24h_usd <= $50 — then holder/distribution top-10 per token: top10_pct top1_owner amount pct top_wallet_value=pct*MC",
      "Batch-identity label top wallets: drop non-(Solana|EVM), POST /identity/v1/multiple 100/batch → type/label/category/tags (4 extra cols)",
      "Final sort: market_cap DESC → top_wallet_value DESC → liquidity DESC → volume_24h_usd ASC. First column = chain. 28 token fields + 9 collector cols."
    ],
    agentPrompts: [
      "Scan all chains for spam tokens with MC >= $1B but 24h volume under $50 — show top wallet concentration",
      "Show me SOL-only high-MC dead tokens ranked by top-1 wallet value ($)",
      "Label every top holder of EVM spam tokens (base, bsc, eth) and flag exchange-owned wallets",
      "Sort the STC list by top_wallet_value DESC — find whales sitting on highest-$ zombie bags"
    ],
    apiAgg: "/api/v1/stc/sweep?min_mc=1e9&max_vol=50&chains=solana,robinhood,base,bsc,ethereum"
  },
  key: {
    installPrompt: `# Birdeye key (session/RAM or ~/.birdeye.env) + 4 AI providers (OpenAI / Anthropic / OpenRouter / Gemini)\npython3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload\n# Then open Skill #28 → paste key → Apply session (RAM, no disk)`,
    installPresets: [
      { label: "Launch Hub · hot-reload ON · local 8765 (0 CU)",                                  cu: 0,   cmd: `python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload` },
      { label: "Launch Hub · bind 0.0.0.0 · LAN share · no hot-reload (prod-like)",              cu: 0,   cmd: `python3 birdeye_ui.py --host 0.0.0.0 --port 8765` },
      { label: "Background nohup · log to /tmp/birdeye-ui.log",                                   cu: 0,   cmd: `nohup python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload > /tmp/birdeye-ui.log 2>&1 & echo PID=$!` },
      { label: "Set Birdeye key to env in shell (RAM only for current terminal)",                 cu: 0,   cmd: `export BIRDEYE_API_KEY="<PASTE_BIRDEYE_KEY_HERE>" ; echo "Key set: \${BIRDEYE_API_KEY:0:2}****\${BIRDEYE_API_KEY: -2}"` },
      { label: "Persist ALL keys (Birdeye + 4 AI) → ~/.birdeye.env chmod 600 · append line",      cu: 0,   cmd: `printf 'BIRDEYE_API_KEY=<KEY>\\nOPENAI_API_KEY=<OKEY>\\nANTHROPIC_API_KEY=<AKEY>\\nOPENROUTER_API_KEY=<ORKEY>\\nGOOGLE_API_KEY=<GKEY>\\n' >> ~/.birdeye.env && chmod 600 ~/.birdeye.env` },
      { label: "0 CU key status · mask h2t2 via /api/key-info + /api/ai-key-info",                cu: 0,   cmd: `curl -s http://127.0.0.1:8765/api/key-info ; echo ; curl -s http://127.0.0.1:8765/api/ai-key-info` }
    ],
    coreCaps: [
      "Two tabs: 🛰 Birdeye (paste / eye toggle / apply session / save persist / clear) + 🤖 AI BYO (4 providers same flow)",
      "Key mask head2****tail2 server-side; UI shows 16×• after apply; raw key NEVER localStorage",
      "Session-only = in-process RAM; Save = append ~/.birdeye.env chmod 600; duplicate line dedupe",
      "AI agent 4 provider routing: system prompt injects all 32 skills catalog → JSON routeAction prefill only (no auto-run)"
    ],
    agentPrompts: [
      "Show key status for Birdeye + all 4 AI providers (masked)",
      "Save my current Birdeye + OpenAI session keys to ~/.birdeye.env",
      "Clear all session keys from RAM right now",
      "What's the current CU cost of the last 3 runs from history?"
    ],
    apiAgg: "/api/key-info + /api/ai-key-info (0 CU)"
  },
  about: {
    installPrompt: `python3 birdeye_ui.py --host 127.0.0.1 --port 8765 --reload\n# Open http://127.0.0.1:8765/ in your browser`,
    installPresets: [
      { label: "Open Hub · local browser (0 CU)",                              cu: 0,   cmd: `open http://127.0.0.1:8765/` },
      { label: "Inventory 32 skills · list all CLI subcommands (0 CU)",       cu: 0,   cmd: `python3 birdeye-screener/scripts/birdeye_cli.py --help` },
      { label: "Open design folder 14 API specs · /API/*.md (0 CU)",           cu: 0,   cmd: `open /Users/nguyenthenang/nang/birdeye/app/skills/API/` },
      { label: "Rebuild catalog CSV from skills builtin (0 CU)",               cu: 0,   cmd: `cd /Users/nguyenthenang/nang/birdeye/app/skills && python3 birdeye-screener/scripts/build_skill_catalog_csv.py` },
      { label: "Health check live server · banner skills count (0 CU)",        cu: 0,   cmd: `curl -s http://127.0.0.1:8765/health | python3 -m json.tool` },
      { label: "Clear old runs (older 24h) cache dir (0 CU)",                  cu: 0,   cmd: `find ~/.cache/birdeye-skills-runs -type f -mtime +0h -delete 2>/dev/null ; echo cleared` }
    ],
    coreCaps: [
      "32 production-grade skills with LIVE modules for Discovery, Token DD, RugCheck, STC, Wallet Score, and Key Management",
      "Python stdlib zero-deps (no pip/npm install); hot-reload --reload flag for JS/CSS literal",
      "All outputs cacheable (replay 0 CU); Telegram / Scorecard / Plain / JSON 4 formats",
      "🛰 100% Birdeye Data badge; modular includes; transparent CU breakdown footer on every run"
    ],
    agentPrompts: [
      "List all LIVE skills with their base CU cost",
      "Summarize each skill category in 3 bullets (Discovery / Token DD / Wallet Intel / Data Analytics / Monitor / Utils)",
      "Show the cheapest 5 skills by CU cost — batch sweep candidate",
      "Which skills require include=advanced_security to reveal tag-cohort% and liq drawdown?"
    ],
    apiAgg: "/api/history/list?limit=10 (last runs CU summary)"
  }
};
// Generic fallback for WIP skills (everything not explicitly in dict above — WIP banner)
const SKILL_META_FALLBACK = {
  installPrompt: `# Skill: <SKILL_ID> · WIP — install scaffold + CLI placeholder\ncd /Users/nguyenthenang/nang/birdeye/app/skills\npython3 birdeye-screener/scripts/birdeye_cli.py --help | grep <SKILL_ID>`,
  installPresets: null,
  coreCaps: [
    "🛠 Design doc ready — click 📖 Read design doc above to see endpoint map",
    "CLI subcommand roadmap; integrate into existing birdeye_cli.py when implemented",
    "Reuses same includes / CU adders as Token DD module system (/API/13.md)",
    "0-CU format switch: plain / telegram / scorecard / JSON once payload is cached"
  ],
  agentPrompts: [
    "Open design document for skill <SKILL_ID> to see endpoint recipe",
    "What Birdeye APIs does skill <SKILL_ID> call? Summarize CU cost per step",
    "Compare skill <SKILL_ID> vs skill #3 Token DD — which one do I run first for a new token?",
    "Queue skill <SKILL_ID> for implementation next — note required endpoints in my backlog"
  ],
  apiAgg: "/API/ — open design folder for this skill"
};

function _skillMeta(skillId){
  let m = SKILL_META_BY_ID[skillId];
  if(!m){
    m = JSON.parse(JSON.stringify(SKILL_META_FALLBACK));
    m.installPrompt = m.installPrompt.replaceAll('<SKILL_ID>', skillId || 'unknown');
    m.agentPrompts = m.agentPrompts.map(s=>s.replaceAll('<SKILL_ID>', skillId || 'unknown'));
  }
  // Build installPresets fallback if not explicitly declared: 4 flavors of installPrompt + format variants
  if(!m.installPresets || !Array.isArray(m.installPresets) || m.installPresets.length === 0){
    const basePrompt = m.installPrompt || '';
    // Strip any existing --format flag from base prompt to allow override cleanly for 4 variants
    const cleanCmd = basePrompt.replace(/\s+--format\s+\S+/g, '').replace(/\s+$/,'');
    const sid = (skillId || 'unknown').replace(/[^a-z0-9_-]/gi, '');
    const W = (cmd) => cmd.replaceAll('<SKILL_ID>', sid);
    m.installPresets = [
      { label: `WIP DEFAULT · Scorecard UI format`,           cu: 0, cmd: W(`${cleanCmd} --format scorecard`) },
      { label: `WIP · Telegram markdown paste to bot`,       cu: 0, cmd: W(`${cleanCmd} --format telegram`) },
      { label: `WIP · plain ASCII terminal view`,            cu: 0, cmd: W(`${cleanCmd} --format plain`) },
      { label: `WIP · raw-json agent machine-readable`,      cu: 0, cmd: W(`${cleanCmd} --format raw-json`) },
      { label: `WIP · inspect design docs folder /API/`,     cu: 0, cmd: W(`# Design doc list for ${sid}:\nls -la /Users/nguyenthenang/nang/birdeye/app/skills/API/ | head -20`) },
      { label: `WIP · CLI help specific subcommand grep`,    cu: 0, cmd: W(`python3 birdeye-screener/scripts/birdeye_cli.py --help | grep -i "${sid}"`) }
    ];
  }
  return m;
}

function _wrapInstallationCard(meta){
  // NO MORE PRESETS (per user request: 1 skill = 1 focused use case, no user option overload).
  // Single canonical install prompt + copy button only.
  const cmd = (meta && meta.installPrompt) ? meta.installPrompt : '';
  const initialCu = Number((meta && meta.cu) || 0) || Number((meta && meta._actualCu) || 0) || 0;
  return `<div style="border:1px solid var(--line);border-radius:10px;background:var(--card-bg)">
    <div style="display:flex;align-items:center;gap:8px;padding:5px 10px;border-bottom:1px solid var(--line)">
      <div style="font-size:10px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;color:var(--mute)">INSTALL / CMD</div>
      <div style="flex:1"></div>
      ${initialCu ? `<span id="sk_install_cu_badge" class="chip cu" style="font-size:11px;padding:2px 8px">⚡ ${initialCu} CU</span>` : ''}
    </div>
    <div style="padding:7px 10px">
      <div class="subtle" style="font-size:11px;margin-bottom:5px">Run this command in your terminal — identical output as the ▶ Run button.</div>
      <div style="display:flex;gap:6px;align-items:flex-start">
        <pre id="sk_install_copyblock" style="flex:1;margin:0;min-height:44px;padding:6px 9px;border-radius:8px;background:var(--deep-bg);border:1px solid var(--line);font-size:11px;font-family:monospace;white-space:pre-wrap;cursor:pointer;color:var(--text);line-height:1.5" title="Click to copy command">${htmlEscape(cmd||'')}</pre>
        <button class="btn ghost" id="sk_install_copybtn" style="padding:4px 9px;font-size:11px;white-space:nowrap">📋 Copy</button>
      </div>
    </div>
  </div>`;
}

function _wrapCoreCapsList(caps){
  const items = (caps||[]).map(c=>`<div style="padding:10px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card-bg);font-size:13px;line-height:1.55;color:var(--text)">${htmlEscape(c)}</div>`).join('');
  return `<div style="margin:8px 0 22px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
      <span style="font-size:16px">⚡</span>
      <div style="font-weight:700;font-size:15px">Core Capabilities</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:8px">${items || '<div class="subtle">No capabilities listed yet.</div>'}</div>
  </div>`;
}

function _wrapAgentPromptsList(prompts){
  const items = (prompts||[]).map(p=>`<div class="agentprompt" style="padding:10px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card-bg);font-size:13px;line-height:1.55;color:var(--text);cursor:pointer" title="Click to copy to clipboard">${htmlEscape(p)}</div>`).join('');
  return `<div style="margin:6px 0 8px">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
      <span style="font-size:16px">💬</span>
      <div style="font-weight:700;font-size:15px">Just say to your Agent</div>
      <div style="flex:1"></div>
      <span class="subtle" style="font-size:11px">click any line → copy to clipboard</span>
    </div>
    <div style="display:flex;flex-direction:column;gap:8px">${items || '<div class="subtle">No prompts yet.</div>'}</div>
  </div>`;
}

function _wireDetailFooterWiring(skillId){
  // Copy install block (codebox)
  const box = document.getElementById('sk_install_copyblock');
  const btn = document.getElementById('sk_install_copybtn');
  const msg = document.getElementById('sk_install_msg');
  const sel = document.getElementById('sk_install_preset');
  const runBtn = document.getElementById('sk_install_runpreset');
  const cuBadge = document.getElementById('sk_install_cu_badge');
  const copyInstall = ()=>{
    try{
      const txt = (box?.innerText||'').replace(/\s+$/,'');
      if(!txt) return;
      navigator.clipboard?.writeText(txt);
      if(msg){ msg.textContent = '✅ Installation prompt copied.'; setTimeout(()=>{ if(msg) msg.textContent = '⬆ click the grey code box (or Copy button) to copy the exact preset command · ▶ Run This Preset = sync control inputs + auto execute the preset against Birdeye API immediately.'; }, 2800); }
    }catch(e){}
  };
  if(box) box.onclick = copyInstall;
  if(btn) btn.onclick = copyInstall;

  // ---- Parse CLI command tokens -> key/value dict. Handles: birdeye_cli.py <subcmd> --k v --flag --no-flag positional
  function _parseCLIArgs(cmdStr){
    if(!cmdStr) return {sub:null, kv:{}};
    // naive tokenizer respecting quoted strings (simple)
    const tokens = [];
    let i=0, cur='', inQ=null;
    const s = String(cmdStr).replace(/\s+/g, ' ').trim();
    while(i < s.length){
      const c = s[i];
      if(inQ){
        if(c === inQ){ inQ = null; i++; continue; }
        cur += c; i++; continue;
      }
      if(c==='"'||c==="'"){ inQ = c; i++; continue; }
      if(c===' '){ if(cur){ tokens.push(cur); cur=''; } i++; continue; }
      cur += c; i++;
    }
    if(cur) tokens.push(cur);
    // Skip leading path/py/python/python3 tokens + script name
    let pos = 0;
    while(pos < tokens.length && (tokens[pos].match(/^(python|python3|py|birdeye_cli|.*birdeye_cli\.py|birdeye-screener\/scripts\/birdeye_cli\.py)$/))){
      pos++;
    }
    const sub = (tokens[pos] && !tokens[pos].startsWith('--')) ? tokens[pos++] : null;
    const kv = {};
    while(pos < tokens.length){
      const t = tokens[pos];
      if(t && t.startsWith('--')){
        const k = t.slice(2);
        // next token is either value or another --flag OR end of line. If next starts with -- or no next -> boolean flag.
        const nxt = tokens[pos+1];
        // special: --no-xxx = boolean false
        if(k.startsWith('no-')){
          kv[k.slice(3)] = false;
          pos++;
          continue;
        }
        if(nxt === undefined || (typeof nxt === 'string' && nxt.startsWith('--'))){
          kv[k] = true; pos++; continue;
        }
        kv[k] = nxt; pos += 2; continue;
      }else{
        // positional: record in order for fallback
        if(!kv.__pos) kv.__pos = [];
        kv.__pos.push(t);
        pos++;
      }
    }
    return {sub: sub, kv: kv};
  }

  // ---- Sync parsed args dict -> control panel actual inputs (per-skill id mapping)
  function _syncCtrlPanelFromArgs(skill, parsed){
    const {sub, kv} = parsed || {sub:null, kv:{}};
    if(!skill) return;
    const setSelect = (id, val)=>{
      const el = document.getElementById(id);
      if(!el || !(el.tagName === 'SELECT' || el.tagName==='INPUT')) return;
      // find exact match OR starts with OR case-insensitive
      if(el.tagName === 'SELECT'){
        const v = String(val||'').toLowerCase();
        let foundIdx = -1;
        for(let i=0; i<el.options.length; i++){
          const ov = String(el.options[i].text || el.options[i].value || '').toLowerCase();
          if(String(el.options[i].value).toLowerCase() === v){ foundIdx = i; break; }
          if(ov === v){ foundIdx = i; break; }
          if(ov.startsWith(v) && foundIdx<0) foundIdx = i;
        }
        if(foundIdx>=0){ el.selectedIndex = foundIdx; }
      }else{ el.value = String(val==undefined?'':val); }
    };
    const setVal = (id, val)=>{
      const el = document.getElementById(id);
      if(!el) return;
      if(el.tagName === 'SELECT'){ setSelect(id, val); return; }
      el.value = String(val==undefined?'':val);
    };
    const setFormatBfmt = (fmtPanelPrefix, desiredFmt)=>{
      const panel = document.getElementById('skillCtrl');
      if(!panel || !desiredFmt) return;
      let found = null;
      panel.querySelectorAll('.bfmt').forEach(b=>{
        const f = b.dataset.fmt || '';
        if(f === desiredFmt) found = b;
        // map alias: render (dd/sc) => render; scorecard => 'scorecard'; plain->'plain'; telegram->'telegram'; json->raw-json
        if(!found){
          const d = String(desiredFmt).toLowerCase();
          if(f === 'raw-json' && d.includes('json')) found = b;
          if(f === 'render' && (d==='render'||d==='scorecard')) found = b;
          if(f==='scorecard' && d==='scorecard') found = b;
        }
      });
      if(found){
        panel.querySelectorAll('.bfmt').forEach(b=>b.classList.remove('on'));
        found.classList.add('on');
      }
    };
    // 5 main skills each has its own id namespaces: tl / tl_v3 share tl_; dd = dd_; sm_wallets uses sm9_ + dd_chain; rugcheck = rca_
    if(skill==='dd' || skill==='token_dd' || sub==='token-dd'){
      setVal('dd_chain', kv['chain']);
      setVal('dd_address', kv['address'] || (kv.__pos && kv.__pos[0]));
      setFormatBfmt('dd', kv['format'] || 'render');
    }
    if(skill==='tl' || skill==='tl_v3' || sub==='trending-list' || sub==='trending-simple'){
      setVal('tl_chain', kv['chain']);
      setVal('tl_limit', kv['limit'] || kv['top-n']);
      setFormatBfmt('tl', kv['format'] || 'render');
      // depth segmented buttons
      const d = String(kv['depth']||'').toLowerCase();
      if(d){
        document.querySelectorAll('#skillCtrl .segBtn').forEach(b=>{
          b.classList.toggle('on', (b.id||'').toLowerCase().includes(d) || (b.textContent||'').toLowerCase().includes(d));
        });
      }
    }
    if(skill==='sm_wallets' || sub==='smart-wallets' || sub==='smart-money-profile'){
      setSelect('dd_chain', kv['chain']);
      setVal('sm9_wallet', kv['wallet']);
      setVal('sm9_pnl', kv['pnl-method'] || 'wac');
      const skTx = document.getElementById('sm9_skip_tx'); if(skTx) skTx.checked = !!(kv['skip-tx-list']);
      const skF = document.getElementById('sm9_skip_first'); if(skF) skF.checked = !!(kv['skip-first-tx']);
      setFormatBfmt('sm', kv['format'] || 'render');
    }
    if(skill==='sm_flow_token' || sub==='wallet-analysis'){
      setSelect('wa_chain', kv['chain']);
      setVal('wa_wallet', kv['wallet']);
      setVal('wa_horizon', kv['horizon'] || 'normal');
      setVal('wa_pnl', kv['pnl-method'] || 'wac');
      const waTx = document.getElementById('wa_skip_tx'); if(waTx) waTx.checked = !!(kv['skip-tx-list']);
      const waF = document.getElementById('wa_skip_first'); if(waF) waF.checked = !!(kv['skip-first-tx']);
      const waP = document.getElementById('wa_skip_port'); if(waP) waP.checked = !!(kv['skip-portfolio']);
      setFormatBfmt('wa', kv['format'] || 'render');
    }
    if(skill==='rugcheck_risk_audit' || sub==='rugcheck-audit'){
      setVal('rca_chain', kv['chain']);
      setVal('rca_address', kv['address']);
      setSelect('rca_liq_window', kv['rug-liq-window'] || '24h');
      // show holders: --rug-show-holders (true default) or --no-rug-show-holders (false)
      const yes = !(kv['rug-show-holders']===false || String(kv['rug-show-holders']||'1')==='0' || String(kv['rug-show-holders']||'').toLowerCase()==='no' || String(kv['rug-show-holders']||'').toLowerCase()==='false');
      setSelect('rca_show_holders', yes ? '1' : '0');
      setVal('rca_holders_n', kv['rug-holders-top-n']);
      setFormatBfmt('rca', kv['format'] || 'render');
    }
  }

  // ---- Preset dropdown -> reactive update (codebox + CU badge) + auto SYNC control panel inputs
  const _applyInstallPreset = (idx)=>{
    if(!sel || !sel.options || idx<0 || idx>=sel.options.length) return;
    const opt = sel.options[idx];
    const cu = Number(opt.dataset.cu || 0);
    const cmdRaw = opt.dataset.cmd || '';
    let cmd = cmdRaw;
    try{ cmd = decodeURIComponent(cmdRaw); }catch(e){}
    if(box) box.textContent = cmd;
    if(cuBadge) cuBadge.textContent = '⚡ ' + cu + ' CU';
    // NEW: Auto sync left control panel inputs from this preset's CLI args
    try{
      const parsed = _parseCLIArgs(cmd);
      _syncCtrlPanelFromArgs(skillId, parsed);
      if(msg){ msg.textContent = '🔄 Preset synced to control panel. Click ▶ Run This Preset to execute immediately (0 extra setup).'; }
    }catch(e){}
  };
  if(sel){
    sel.onchange = (e)=>_applyInstallPreset(e.target.selectedIndex);
    _applyInstallPreset(sel.selectedIndex || 0);
  }

  // ---- ▶ Run This Preset button: execute current CLI preset against backend (maps skill -> runCLI side)
  if(runBtn){
    runBtn.addEventListener('click', ()=>{
      // First re-apply current idx -> forces sync so ctrl panel values 100% match the preset.
      if(sel){ _applyInstallPreset(sel.selectedIndex || 0); }
      // side map
      const s = skillId;
      let side = null;
      if(s==='rugcheck_risk_audit') side='rca';
      else if(s==='sm_wallets') side='sm';
      else if(s==='sm_flow_token') side='wa';
      else if(s==='tl'||s==='tl_v3') side='tl';
      else if(s==='dd'||s==='token_dd') side='dd';
      else{
        // fallback heuristic: parse subcmd from preset box
        try{
          const cmd = (box?.innerText||'');
          const p = _parseCLIArgs(cmd);
          if(p.sub==='rugcheck-audit') side='rca';
          else if(p.sub==='smart-wallets' || p.sub==='smart-money-profile') side='sm';
          else if(p.sub==='wallet-analysis') side='wa';
          else if(p.sub==='trending-list' || p.sub==='trending-simple') side='tl';
          else side='dd';
        }catch(e){ side='dd'; }
      }
      if(msg){ msg.textContent = '🚀 Executing preset against Birdeye API… please wait ~2-8 seconds.'; }
      runBtn.disabled = true; runBtn.style.opacity='.55';
      setTimeout(()=>{ runBtn.disabled = false; runBtn.style.opacity = '1'; }, 9000);
      runCLI(side);
    });
  }
  // Copy each agent prompt line
  document.querySelectorAll('#skillCtrl .agentprompt').forEach((el,i)=>{
    el.onclick = ()=>{
      try{
        const txt = (el.innerText||'').replace(/\s+$/,'');
        navigator.clipboard?.writeText(txt);
        const prev = el.style.outline;
        el.style.outline = '2px solid var(--good)';
        setTimeout(()=>{ el.style.outline = prev||''; }, 500);
      }catch(e){}
    };
  });
}

function wireFormatButtonsInPanel(side){
  document.querySelectorAll('#skillCtrl .bfmt').forEach(b=>{
    b.onclick = ()=>{
      // First: unset any current active bfmt in the same panel
      document.querySelectorAll('#skillCtrl .bfmt').forEach(x=>x.classList.remove('on'));
      b.classList.add('on');
      const fmt = b.dataset.fmt || 'render';
      // If there is a lastRun of this side -> re-render output using cache (no API call).
      const lr = window.STATE.lastRun;
      if(lr && lr.side === side){
        renderFormat(fmt, lr.runId, lr.kind, lr.side);
      }
    };
  });
}

function renderSkillCtrl(){
  const fn = SKILL_CTRLS[window.STATE.skill] || (()=>`<h3>${window.STATE.skill}</h3><div class="subtle">Choose from catalog.</div>`);
  $('skillCtrl').innerHTML = fn();
  const t = window.STATE.skill;
  // ---- Col2: control panel + Core Capabilities + Agent prompts (Installation moved to Col3 top) ----
  const meta = _skillMeta(t);
  $('skillCtrl').innerHTML += _wrapCoreCapsList(meta.coreCaps)
                          + _wrapAgentPromptsList(meta.agentPrompts);
  // ---- Col3: Top pinned Installation block (dropdown preset UI friendly) ----
  const installCol = $('installColTop');
  if(installCol){ installCol.innerHTML = _wrapInstallationCard(meta); }
  // Wire run buttons
  if(t==='tl' || t==='tl_v3'){
    wireFormatButtonsInPanel('tl');
    $('tl_run')?.addEventListener('click',()=>{
      if(t==='tl_v3'){ const e=$('tl_source'); if(e) e.value='v3-list'; }
      else { const e=$('tl_source'); if(e) e.value='trending'; }
      runCLI('tl');
    });
    if(t==='tl_v3'){
      const s=$('tl_source'); if(s) s.value='v3-list';
      $('tl_sort') && ($('tl_sort').value='volumeUSD');
      $('tl_interval') && ($('tl_interval').value='1h');
    }
    if(t==='tl'){
      const s=$('tl_source'); if(s) s.value='trending';
      $('tl_sort') && ($('tl_sort').value='rank');
      $('tl_interval') && ($('tl_interval').value='24h');
    }
  }else if(t==='dd'){
    wireFormatButtonsInPanel('dd');
    $('dd_run')?.addEventListener('click',()=>runCLI('dd'));
    if(window.STATE.selection){
      $('dd_address').value = window.STATE.selection.addr || '';
      $('dd_chain').value = window.STATE.selection.chain || 'sol';
    }
  }else if(t==='key'){
    refreshKeyBox();
    if($('pasteKey2')){
      if(window._SESSION_KEY_MEM || (localStorage.getItem(LSKEY_SESSION_PASTE)||'') === '__MASKED_APPLIED__'){
        $('pasteKey2').value = '••••••••••••••••';
        $('pasteKey2').type = 'password';
        $('pasteKey2').dataset.masked = '1';
      } else {
        $('pasteKey2').value = '';
        $('pasteKey2').type = 'password';
        $('pasteKey2').dataset.masked = '';
      }
    }
    $('pasteKey2_eye') && ($('pasteKey2_eye').onclick = ()=>_toggleKeyEye('pasteKey2'));
    $('skillCtrl').querySelectorAll('[data-act][data-prov="birdeye"]').forEach(b=>{
      b.onclick=()=>doKeyAction(b.dataset.act, $('pasteKey2').value);
    });
    _wireKeyTabs();
    _initAiKeyPanel();
  }else if(t==='sm_wallets'){
    // Skill #9 Smart Money Profile — wire run + format
    wireFormatButtonsInPanel('sm');
    const runBtn = $('sm9_run');
    if(runBtn){ runBtn.disabled = false; runBtn.style.opacity = '1'; }
    runBtn?.addEventListener('click', ()=>runCLI('sm'));
    if(window.STATE.selection){
      if($('sm9_wallet')) $('sm9_wallet').value = window.STATE.selection.wallet || window.STATE.selection.addr || '';
    }
  }else if(t==='sm_flow_token'){
    // Skill #14 Wallet Analysis — wire run + format
    wireFormatButtonsInPanel('wa');
    $('wa_run')?.addEventListener('click', ()=>runCLI('wa'));
    if(window.STATE.selection){
      if($('wa_wallet')) $('wa_wallet').value = window.STATE.selection.wallet || window.STATE.selection.addr || '';
    }
  }else if(t==='rugcheck_risk_audit'){
    // Skill #17b · RugCheck Audit — wire run
    wireFormatButtonsInPanel('rca');
    $('rca_run')?.addEventListener('click', ()=>runCLI('rca'));
    if(window.STATE.selection){
      if($('rca_address')) $('rca_address').value = window.STATE.selection.addr || '';
      if($('rca_chain'))   $('rca_chain').value   = window.STATE.selection.chain || 'sol';
    }
    // open compare page side-by-side option (0 CU install preset #8 behaviour — helper button)
  }else if(t==='stc'){
    // Skill #6 · Spam Token Cleaner — wire format buttons + run
    wireFormatButtonsInPanel('stc');
    $('stc_run')?.addEventListener('click', ()=>runCLI('stc'));
  }else if(t==='wallet_score'){
    // Skill #13 · Wallet Score — wire run + format + selection populate
    wireFormatButtonsInPanel('wallet_score');
    $('wallet_score_run')?.addEventListener('click', ()=>runCLI('wallet_score'));
    if(window.STATE.selection){
      // Populate from state if user clicked a wallet selection elsewhere
      if($('ws_address')) $('ws_address').value = window.STATE.selection.wallet || window.STATE.selection.addr || '';
      if($('ws_chain'))   $('ws_chain').value   = window.STATE.selection.chain || 'sol';
    }
  }else if(t==='wallet_style'){
    // Skill #11 · Wallet Style — wire run + format + selection populate
    wireFormatButtonsInPanel('wallet_style');
    $('wallet_style_run')?.addEventListener('click', ()=>runCLI('wallet_style'));
    if(window.STATE.selection){
      if($('wst_address')) $('wst_address').value = window.STATE.selection.wallet || window.STATE.selection.addr || '';
      if($('wst_chain'))   $('wst_chain').value   = window.STATE.selection.chain || 'sol';
    }
  }else if(t==='kline_pattern'){
    // Skill #21 · Kline Pattern — wire run + format + selection populate
    wireFormatButtonsInPanel('kline_pattern');
    $('kline_pattern_run')?.addEventListener('click', ()=>runCLI('kline_pattern'));
    if(window.STATE.selection){
      if($('kp_address')) $('kp_address').value = window.STATE.selection.address || window.STATE.selection.addr || window.STATE.selection.token || '';
      if($('kp_chain'))   $('kp_chain').value   = window.STATE.selection.chain || 'sol';
    }
  }else if(t==='trending_score'){
    // Skill #22 · Token Trending Score — wire run + format + selection populate
    wireFormatButtonsInPanel('trending_score');
    $('trending_score_run')?.addEventListener('click', ()=>runCLI('trending_score'));
    if(window.STATE.selection){
      if($('ts_address')) $('ts_address').value = window.STATE.selection.address || window.STATE.selection.addr || window.STATE.selection.token || '';
      if($('ts_chain'))   $('ts_chain').value   = window.STATE.selection.chain || 'sol';
    }
  }else if(t==='contract_dd'){
    // Skill #5 · Contract DD — wire run + format + selection populate
    wireFormatButtonsInPanel('contract_dd');
    $('contract_dd_run')?.addEventListener('click', ()=>runCLI('contract_dd'));
    if(window.STATE.selection){
      if($('cdd_address')) $('cdd_address').value = window.STATE.selection.address || window.STATE.selection.addr || window.STATE.selection.token || '';
      if($('cdd_chain'))   $('cdd_chain').value   = window.STATE.selection.chain || 'sol';
    }
  }else if(t==='junk_predict'){
    // Skill #32 · Junk Token Prediction (ML) — wire run + quick-test + format
    wireFormatButtonsInPanel('junk');
    $('junk_run')?.addEventListener('click', ()=>runCLI('junk_predict'));
    $('junk_quick_test')?.addEventListener('click', ()=>runCLI('junk_quick_test'));
    if(window.STATE.selection){
      const a = window.STATE.selection.addr || window.STATE.selection.address || window.STATE.selection.token || '';
      if(a && $('junk_tokens')) $('junk_tokens').value = a;
    }
  }
  // Wire WIP design-doc button (generic panel)
  $('readApiDocBtn') && ($('readApiDocBtn').onclick = ()=>openApiDocForSkill(window.STATE.skill));
  // Wire Skill #9 Smart Traders dynamic sliders panel
  _wireSm9Panel();
  // Wire click-to-copy for footer sections (install block + agent prompt lines)
  _wireDetailFooterWiring(t);
  // R8: Auto-select-all for address inputs — click/focus highlights entire value, no Ctrl-A+delete needed
  try {
    document.querySelectorAll('#skillCtrl input, #skillCtrl textarea').forEach(inp => {
      if (!inp || !inp.id) return;
      if (!(inp.id.includes('address') || inp.id.includes('addr') || inp.id.includes('search'))) return;
      if (inp.dataset.autoSelectAllWired) return;
      inp.dataset.autoSelectAllWired = '1';
      const doSelect = () => {
        try {
          if (inp.tagName === 'INPUT') {
            inp.focus();
            inp.setSelectionRange(0, inp.value ? inp.value.length : 0);
          } else if (inp.tagName === 'TEXTAREA') {
            inp.focus();
            inp.setSelectionRange(0, inp.value ? inp.value.length : 0);
          }
        } catch (_) { try { inp.select && inp.select(); } catch(_){} }
      };
      inp.addEventListener('focus', doSelect);
      inp.addEventListener('click', (e) => { setTimeout(doSelect, 0); });
      inp.addEventListener('mouseup', (e) => { e.preventDefault(); });
    });
  } catch(_) {}
  // R-copy: Add 📋 copy button next to every wallet/token address input (copy current value to clipboard)
  try {
    document.querySelectorAll('#skillCtrl input, #skillCtrl textarea').forEach(inp => {
      if (!inp || !inp.id) return;
      if (!(inp.id.includes('address') || inp.id.includes('addr') || inp.id.includes('search'))) return;
      if (inp.dataset.copyBtnWired) return;
      inp.dataset.copyBtnWired = '1';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn ghost';
      btn.style.cssText = 'padding:4px 8px;font-size:12px;flex-shrink:0';
      btn.title = 'Copy current address to clipboard';
      btn.textContent = '📋';
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const val = (inp.value || '').trim();
        if (!val) { btn.textContent = '∅'; setTimeout(()=>{btn.textContent='📋';}, 800); return; }
        try { await navigator.clipboard.writeText(val); btn.textContent = '✓'; }
        catch(_) { try{ inp.select(); document.execCommand('copy'); btn.textContent='✓'; }catch(__){ btn.textContent='✗'; } }
        setTimeout(()=>{btn.textContent='📋';}, 1000);
      });
      // Insert button right after the input (wrap if input is the only child of its row)
      if (inp.parentElement && inp.parentElement.classList.contains('row')) {
        inp.parentElement.style.gridTemplateColumns = '84px 1fr auto';
        inp.parentElement.appendChild(btn);
      } else {
        inp.parentNode && inp.parentNode.insertBefore(btn, inp.nextSibling);
      }
    });
  } catch(_) {}
}

// ---------- History / cache side panel ----------
async function refreshHistory(){
  try{
    const j = await fetch('/api/history/list?limit=50').then(r=>r.json());
    const list = j.items || [];
    $('histCount').textContent = list.length + ' runs';
    const html = list.map(it=>{
      const ago = (Date.now()/1000 - it.saved_at_unix);
      let agoS; if(ago<60) agoS=`${Math.max(1,Math.floor(ago))}s`; else if(ago<3600) agoS=`${Math.floor(ago/60)}m`; else agoS=`${Math.floor(ago/3600)}h${Math.floor((ago%3600)/60)}m`;
      const badge = it.score!=null ? `<span class="sc">⭐${Number(it.score).toFixed(1)}</span>` : '';
      const cuBadge = it.cu_used_total ? `<span class="kcu">⚡${it.cu_used_total}</span>` : '';
      const active = (window.STATE.lastRun && window.STATE.lastRun.runId===it.runId)?'active':'';
      return `<div class="hrun ${active}" data-rid="${htmlEscape(it.runId)}" data-kind="${htmlEscape(it.kind)}">
        <b>${badge}${cuBadge}${htmlEscape(it.summary)}</b>
        <span>${htmlEscape(it.detail || it.kind)} · ${agoS} ago</span>
      </div>`;
    }).join('') || `<div class="subtle">No cached runs yet. Click ▶ Run in the left panel to generate history.</div>`;
    $('historyList').innerHTML = html;
    $('historyList').querySelectorAll('.hrun').forEach(el=>{
      el.onclick = ()=>loadRunFromHistory(el.dataset.rid, el.dataset.kind);
    });
  }catch(e){ console.warn('refreshHistory fail', e); }
}

async function loadRunFromHistory(runId, kindHint){
  // Resolve a default side mapping first so panel buttons also sync active format when load.
  let side = 'dd';
  if(kindHint==='token-dd') side='dd';
  else if(kindHint==='rugcheck-audit' || kindHint==='rugcheck-risk-audit') side='rca';
  else if(kindHint==='trending-list') side='tl';
  else if(kindHint==='smart-wallets' || kindHint==='smart-money-profile-v1') side='sm';
  else if(kindHint==='wallet-analysis-v1') side='wa';
  else if(kindHint==='wallet-style-v1') side='wallet_style';
  else if(kindHint==='wallet-score' || kindHint==='wallet-alpha-score-v1' || kindHint==='wallet-score-compact-v1') side='wallet_score';
  // If sm wallet run: open Skill #9 detail page (col layout 3-col) so user can rerun / adjust sliders
  if(side==='sm'){
    if(window.STATE.mode!=='drill'){ drillMode('smart-money'); }
    window.STATE.skill='sm_wallets';
    renderCatalog();
    renderSkillCtrl();
  }else if(side==='wa'){
    if(window.STATE.mode!=='drill'){ drillMode('smart-money'); }
    window.STATE.skill='sm_flow_token';
    renderCatalog();
    renderSkillCtrl();
  }else if(side==='wallet_score'){
    if(window.STATE.mode!=='drill'){ drillMode('smart-money'); }
    window.STATE.skill='wallet_score';
    renderCatalog();
    renderSkillCtrl();
  }else if(side==='wallet_style'){
    if(window.STATE.mode!=='drill'){ drillMode('smart-money'); }
    window.STATE.skill='wallet_style';
    renderCatalog();
    renderSkillCtrl();
  }else if(side==='rca'){
    if(window.STATE.mode!=='drill'){ drillMode('security-risk'); }
    window.STATE.skill='rugcheck_risk_audit';
    renderCatalog();
    renderSkillCtrl();
  }
  // 1. Use the user's currently-selected format in the panel, else default 'render'
  const userFmt = selectedFmt(side);
  // 2. Update lastRun record (so next format-switch works against this run)
  window.STATE.lastRun = { runId, side, kind: kindHint, lastFmt: userFmt };
  await renderFormat(userFmt, runId, kindHint, side, /*fromHistory*/ true);
  refreshHistory();
}

async function renderFormat(fmt, runId, kind, side, {fromHistory=false}={}){
  const out = $('out');
  if(!runId){
    out.innerHTML = `<div class="render"><div class="warn">No cached run yet — run first then switch format.</div></div>`;
    return;
  }
  window.STATE.lastRun = { ...(window.STATE.lastRun || {}), runId, side, kind, lastFmt: fmt };
  out.innerHTML = `<div class="render"><div><span class="loading">⟳</span> Rendering ${fmt} from cache (0 CU)…</div></div>`;
  try{
    let renderResult;
    if(fmt==='render' || fmt==='plain' || fmt==='telegram' || fmt==='raw-json'){
      // Fetch CLI history-render: if render → JSON; else → text stdout
      const url = '/api/history/render?runId=' + encodeURIComponent(runId) + '&format=' + fmt;
      const j = await fetch(url).then(r=>r.json());
      renderResult = j;
    }
    const fmtBarHtml = fmtButtonsHtml(fmt, runId, kind);
    let bodyBlock;
    if(fmt==='render'){
      const payload = renderResult?.payload;
      if(!payload){
        bodyBlock = `<div class="render"><div class="bad">Cache parse error. ${htmlEscape(renderResult?.error||String(renderResult||''))}</div></div>`;
      }else{
        if(kind==='trending-list' || payload?.kind==='trending-list' || payload?.rows){
          const src = payload.params?.source || '';
          bodyBlock = makeTrendRender(payload, src) +
            `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout (cached)</div><pre class="out_body">${htmlEscape('(0 CU re-render — switch to Plain to see CLI output)')}</pre></div>`;
        }else if(kind==='smart-wallets' || payload?.kind==='smart-wallets' || payload?.results_pass){
          bodyBlock = makeSwRender(payload) +
            `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout (cached)</div><pre class="out_body">${htmlEscape('(0 CU re-render — switch to Plain to see CLI output)')}</pre></div>`;
        }else if(kind==='rugcheck-audit' || payload?.kind==='rugcheck-audit' || payload?.rugcheck){
          bodyBlock = makeRugCheckRender(payload, {cached: true}) +
            `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout (cached)</div><pre class="out_body">${htmlEscape('(0 CU re-render — switch to Plain to see CLI output)')}</pre></div>`;
        }else if(kind==='wallet-score' || kind==='wallet-alpha-score-v1' || kind==='wallet-style-v1' || kind==='kline-pattern-v1' || kind==='contract-dd-v1' || kind==='wallet-analysis-v1' || kind==='smart-money-profile-v1' || kind==='junk-predict-v1' || kind==='junk-quick-test-v1' || payload?.kind==='wallet-score' || payload?.kind==='wallet-alpha-score-v1' || payload?.kind==='wallet-style-v1' || payload?.kind==='kline-pattern-v1' || payload?.kind==='contract-dd-v1' || payload?.kind==='wallet-analysis-v1' || payload?.kind==='smart-money-profile-v1' || payload?.kind==='junk-predict-v1' || payload?.kind==='junk-quick-test-v1' || payload?.alpha_score != null || payload?.main_title != null || (payload?.html && typeof payload.html === 'string' && (payload?.pattern != null || payload?.composite != null || payload?.results != null))){
          if(typeof payload?.html === 'string' && payload.html.trim()){
            bodyBlock = payload.html +
              `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout (cached)</div><pre class="out_body">${htmlEscape('(0 CU re-render — switch to Plain to see CLI output)')}</pre></div>`;
          }else{
            bodyBlock = `<pre class="out_body">${htmlEscape(JSON.stringify(payload||{}, null, 2))}</pre>`;
          }
        }else{
          // token-dd scorecard: CLI raw plaintext of payload -> synthesize
          bodyBlock = makeDDRenderFromPayload(payload);
        }
      }
    }else{
      const text = renderResult?.stdout ?? (renderResult?.payload ? JSON.stringify(renderResult.payload, null, 2) : String(renderResult||''));
      bodyBlock = `<pre class="out_body">${htmlEscape(text||'')}${renderResult?.stderr?`\n\n---- stderr ----\n${htmlEscape(renderResult.stderr)}`:''}</pre>`;
    }
    const lr = window.STATE.lastRun || {};
    let cachedCmd = null;
    if (lr.script && lr.argv) {
      cachedCmd = cmdText(lr.script, lr.argv);
    } else {
      // Fallback: history-loaded runs store original argv in payload.params.argv
      const payloadArgv = renderResult?.payload?.params?.argv;
      if (Array.isArray(payloadArgv) && payloadArgv.length) {
        cachedCmd = cmdText('birdeye_cli', payloadArgv);
      }
    }
    const cmdDisplay = cachedCmd ? cachedCmd : ('CACHED (0 CU) — runId='+runId);
    out.innerHTML = `${fmtBarHtml}
      <div class="cmd" style="display:flex;align-items:center;gap:8px"><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${htmlEscape(cmdDisplay)}</span><button class="btn ghost" type="button" style="padding:2px 8px;font-size:12px;flex-shrink:0" title="Copy full CLI command" onclick="const t=this.previousElementSibling.textContent;navigator.clipboard.writeText(t).then(()=>{this.textContent='✓';setTimeout(()=>this.textContent='📋',1000)})">📋</button></div>
      <div class="meta">
        <span class="chip">cached ✓</span>
        <span class="chip cu">⚡CU: 0</span>
        <span class="chip">📦 ${htmlEscape(kind||'')}</span>
        ${fromHistory?`<span class="chip good">loaded from history</span>`:''}
      </div>
      ${bodyBlock}`;
    if(fmt==='render'){ attachSel(out); }
  }catch(e){
    out.innerHTML = `<div class="render"><div class="bad">Error cache render: ${htmlEscape(e.message||String(e))}</div></div>`;
  }
  refreshHistory();
}

function fmtButtonsHtml(activeFmt, runId, kind){
  const but = (fmt,label) =>
    `<button class="bfmt ${activeFmt===fmt?'on':''}" onclick="renderFormat('${fmt}','${runId}','${kind||''}','${window.STATE.lastRun?.side||'tl'}')">${label}</button>`;
  const totalCu = window.STATE.lastRun?.cu_used_total ?? window.__lastFmtCu ?? '';
  const isRCA = (window.STATE.lastRun?.side==='rca') || kind==='rugcheck-audit' || kind==='rugcheck-risk-audit';
  const isDD = (window.STATE.lastRun?.side==='dd') || kind==='token-dd';
  const isWalletScore = (window.STATE.lastRun?.side==='wallet_score') || kind==='wallet-score' || kind==='wallet-alpha-score-v1' || kind==='wallet-score-compact-v1';
  const isWalletStyle = (window.STATE.lastRun?.side==='wallet_style') || kind==='wallet-style-v1';
  const firstBtnLabel = isDD ? 'Scorecard' : (isRCA ? 'RugCheck' : (isWalletScore ? 'Wallet Score' : (isWalletStyle ? 'Wallet Style' : 'Render')));
  return `<div class="fmtbar">
    ${but('render', firstBtnLabel)}
    ${but('plain','Plain')}
    ${but('telegram','Telegram')}
    ${but('raw-json','JSON')}
    <div class="spacer"></div>
    <span class="cacheBadge">💾 Cached run · Original API cost <b>⚡${totalCu || 'N/A'}</b> CU · Re-render = 0 CU</span>
    <button class="btn ghost" onclick="forceRerunCurrent()" title="Delete cache + call API again">⟳ Run fresh (charge CU)</button>
    <button class="btn ghost" onclick="deleteRun('${runId}')">🗑</button>
  </div>`;
}

async function forceRerunCurrent(){
  const lr = window.STATE.lastRun;
  if(!lr){ return alert('No run to refresh.'); }
  const side = lr.side;
  // 1. Delete cached file
  try{ await fetch('/api/history/delete?runId='+encodeURIComponent(lr.runId)).then(r=>r.json()); }catch(_){}
  // 2. Trigger run again (will use same current input in control panel)
  if(side==='dd' && window.STATE.selection?.addr){
    $('dd_address').value = window.STATE.selection.addr;
  }
  runCLI(side);
}

async function deleteRun(runId){
  try{ await fetch('/api/history/delete?runId='+encodeURIComponent(runId)).then(r=>r.json()); }catch(_){}
  const lr = window.STATE.lastRun;
  if(lr && lr.runId===runId){ window.STATE.lastRun=null; $('out').innerHTML=''; }
  refreshHistory();
}

$('histClearOld')?.addEventListener?.('click', ()=>{
  // Server prunes >48h automatically on list; additionally we loop user to delete all non-last-10.
  refreshHistory();
});

// ---------- Key management ----------
async function api(path, body=null){
  const opts = body? {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)} : {};
  const r = await fetch(path, opts); return r.json();
}
async function runScript(script, argv, {uiKey=null}={}){
  const body = {script, argv};
  if(uiKey) body.uiKey = uiKey;
  return api('/api/run', body);
}
function cmdText(script, argv){
  const base = script==='birdeye_cli' ? 'python3 birdeye-screener/scripts/birdeye_cli.py'
    : script==='birdeye_screener' ? 'python3 birdeye-screener/scripts/birdeye_screener.py'
    : script==='stc' ? 'python3 birdeye-screener/scripts/stc.py'
    : 'python3 birdeye-screener/scripts/birdeye_trending_simple.py';
  return base + ' ' + argv.map(a=>/^[A-Za-z0-9_=.-]+$/.test(a)?a:JSON.stringify(a)).join(' ');
}
async function refreshKeyBox(){
  ensureGlobalKeyCollapse();
  const j = await api('/api/key-info');
  const label = j.source || 'MISSING';
  const ok = !!j.key_set;
  if($('cred')){
    $('cred').textContent = ok? `🔑 ${j.mask || ''} · ${label}` : '🔑 API key NOT SET';
    $('cred').className = 'pill ' + (ok?'good':'bad');
  }
  if($('ver')) $('ver').textContent = (j.hot? '🟢 hot-reload ON':'🧊 static') + ' · stdlib HTTP';
  $('keyStatus') && ($('keyStatus').innerHTML = ok? `<span class="good">OK · ${htmlEscape(label)}</span>` : `<span class="bad">Missing — paste below</span>`);
  if($('keyActions') && $('keyInfo')){
    if(!ok){
      $('keyActions').style.display='';
      $('keyActions').classList.remove('ok');
      $('keyInfo').innerHTML = `<span class="bad">Key not found. Paste it → Apply session (RAM) or 💾 Save to ~/.birdeye.env</span>`;
    }else{
      $('keyActions').style.display='';
      $('keyActions').classList.add('ok');
      $('keyInfo').innerHTML = `<span class="good">Loaded from ${htmlEscape(label)}. ${j.mask?htmlEscape(j.mask):''}</span>`;
    }
  }
}
// Temporary in-memory session key for UI re-submits (never persisted).
// localStorage stores ONLY a "keyApplied" boolean; raw key is NEVER on disk.
window._SESSION_KEY_MEM = '';

function _applyKeyMaskUI(){
  // Mask any pasteKey/pasteKey2 input value to 16 visual dots after Apply/Save OK.
  const mask = '••••••••••••••••';
  ['pasteKey','pasteKey2'].forEach(id=>{
    const el = $(id);
    if(el){ el.value = mask; el.type = 'password'; el.dataset.masked='1'; }
  });
  // Toggle eye buttons if present
  ['pasteKey_eye','pasteKey2_eye'].forEach(id=>{ const e=$(id); if(e) e.textContent = '👁'; });
}
function _toggleKeyEye(id){
  const el = $(id);
  if(!el) return;
  const eye = $(id+'_eye');
  if(!eye) return;
  if(el.dataset.masked==='1'){
    // Reveal actual memory key (if available) — temporary unmask session only
    if(window._SESSION_KEY_MEM){ el.value = window._SESSION_KEY_MEM; }
    el.type = (el.type==='password') ? 'text' : 'password';
    eye.textContent = (el.type==='password') ? '👁' : '🙈';
    return;
  }
  el.type = (el.type==='password') ? 'text' : 'password';
  eye.textContent = (el.type==='password') ? '👁' : '🙈';
}
async function doKeyAction(act, val){
  // If value is the masked dots, substitute actual in-memory key for server call
  const looksMasked = /^[•\*]{8,}$/.test(val||'');
  let realVal = (looksMasked ? window._SESSION_KEY_MEM : val) || '';
  realVal = (realVal||'').trim();
  if((act==='apply' || act==='save') && !realVal){
    realVal = window._SESSION_KEY_MEM || '';
  }
  const j = await api('/api/set-key', {action: act, key: realVal});
  if(j.ok){
    if(act==='apply' || act==='save'){
      if(realVal){
        window._SESSION_KEY_MEM = realVal;
        localStorage.setItem(LSKEY_SESSION_PASTE, '__MASKED_APPLIED__');
        _applyKeyMaskUI();
      }
    }
    if(act==='clear'){
      window._SESSION_KEY_MEM = '';
      localStorage.removeItem(LSKEY_SESSION_PASTE);
      ['pasteKey','pasteKey2'].forEach(id=>{
        const el = $(id); if(el){ el.value = ''; el.dataset.masked=''; el.type='password'; }
      });
      ['pasteKey_eye','pasteKey2_eye'].forEach(id=>{ const e=$(id); if(e) e.textContent='👁'; });
    }
  }
  alert(j.ok? 'OK: ' + (j.message||act) : 'Failed: ' + (j.error||'unknown'));
  await refreshKeyBox();
}
// ============================================================
// ---- Skill #28 tabs: Birdeye ↔ AI BYO
// ============================================================
window._SESSION_AI_KEYS = {};
window._AI_ACTIVE_PROV = 'openai';
window._AI_PROV_META = {
  openai:    {base:'https://api.openai.com/v1',         model:'gpt-4o-mini',                   label:'OpenAI',
              path:'/chat/completions',    auth:'Bearer ',   kind:'openai'},
  anthropic: {base:'https://api.anthropic.com/v1',       model:'claude-3-5-haiku-latest-20250514', label:'Anthropic',
              path:'/messages',            auth:'x-api-key', kind:'anthropic'},
  openrouter:{base:'https://openrouter.ai/api/v1',       model:'openai/gpt-4o-mini',             label:'OpenRouter',
              path:'/chat/completions',    auth:'Bearer ',   kind:'openai'},
  gemini:    {base:'https://generativelanguage.googleapis.com/v1beta', model:'gemini-2.0-flash', label:'Gemini',
              path:'/models/{model}:generateContent', auth:'?key=',   kind:'gemini'},
};
const LSKEY_AI_MASK = 'be.ai.mask';

function _wireKeyTabs(){
  document.querySelectorAll('.kTab').forEach(b=>{
    b.onclick=()=>{
      document.querySelectorAll('.kTab').forEach(x=>{x.classList.remove('on');x.style.background='transparent';x.style.color='var(--mute)';});
      b.classList.add('on'); b.style.background='var(--grad-a)'; b.style.color='#fff';
      const k=b.dataset.ktab;
      ['be','ai'].forEach(p=>{
        const pane=$('kTabPane_'+p); if(!pane) return;
        pane.style.display = (k===p)?'':'none';
      });
      if(k==='ai') _refreshAiStatus();
    };
  });
}
function _refreshAiStatus(){
  try{ fetch('/api/ai-key-info').then(r=>r.json()).then(j=>{
    const p = window._AI_ACTIVE_PROV;
    const s = (j.providers||{})[p] || {};
    const el = $('aiKeyStatus'); if(!el) return;
    if(s.key_set){ el.innerHTML = `<span class="good">OK · ${s.source||'?'} · ${htmlEscape(s.mask||'')}</span>`; }
    else { el.innerHTML = `<span class="subtle">Not set. Paste key → Apply session.</span>`; }
    // Sync input visual dots if applied
    if(s.key_set && (!window._SESSION_AI_KEYS[p])){
      // Env/file detected; put in session RAM too for consistency
      window._SESSION_AI_KEYS[p] = window._SESSION_AI_KEYS[p] || '__ENV_LOADED__';
    }
    const wasApplied = (localStorage.getItem(LSKEY_AI_MASK+'_'+p)||'') === '__MASKED_APPLIED__';
    if((s.key_set && s.source === 'session') || wasApplied){
      const inp=$('ai_pasteKey'); if(inp){ inp.value='••••••••••••••••'; inp.type='password'; inp.dataset.masked='1'; }
      const eye=$('ai_pasteKey_eye'); if(eye) eye.textContent='👁';
    }
  }); }catch(e){}
}
function _initAiKeyPanel(){
  // Provider segmented
  document.querySelectorAll('.aiPBtn').forEach(b=>{
    b.onclick=()=>{
      const p=b.dataset.aip; window._AI_ACTIVE_PROV=p;
      document.querySelectorAll('.aiPBtn').forEach(x=>{x.classList.remove('on');x.style.background='transparent';x.style.color='var(--mute)';});
      b.classList.add('on'); b.style.background='var(--grad-a)'; b.style.color='#fff';
      const inp=$('ai_pasteKey'); const eye=$('ai_pasteKey_eye');
      if(window._SESSION_AI_KEYS[p]){ if(inp){inp.value='••••••••••••••••'; inp.type='password'; inp.dataset.masked='1';} if(eye)eye.textContent='👁'; }
      else { if(inp){inp.value=''; inp.type='password'; inp.dataset.masked='';} if(eye)eye.textContent='👁'; }
      _refreshAiStatus();
    };
  });
  // Eye + buttons
  $('ai_pasteKey_eye') && ($('ai_pasteKey_eye').onclick = ()=>{
    const el=$('ai_pasteKey'); const eye=$('ai_pasteKey_eye'); if(!el) return;
    const p = window._AI_ACTIVE_PROV;
    if(el.dataset.masked==='1' && (window._SESSION_AI_KEYS[p] && window._SESSION_AI_KEYS[p]!=='__ENV_LOADED__')){
      el.value = window._SESSION_AI_KEYS[p];
    }
    el.type = (el.type==='password') ? 'text' : 'password';
    eye.textContent = (el.type==='password')?'👁':'🙈';
  });
  const wireAiBtn=(id, act)=>{ $(id) && ($(id).onclick = async ()=>{
    const el=$('ai_pasteKey'); const v = el?el.value:''; const p=window._AI_ACTIVE_PROV;
    await doAiKeyAction(act, v, p);
  });};
  wireAiBtn('aiBtn_apply','apply'); wireAiBtn('aiBtn_save','save'); wireAiBtn('aiBtn_clear','clear');
  // First render status
  _refreshAiStatus();
}
async function doAiKeyAction(act, val, provider){
  const looksMasked = /^[•\*]{8,}$/.test(val||'');
  let realVal = (looksMasked ? window._SESSION_AI_KEYS[provider] : val) || '';
  realVal = (realVal==='__ENV_LOADED__'?'':realVal).trim();
  if((act==='apply'||act==='save') && !realVal){ realVal = (window._SESSION_AI_KEYS[provider]==='__ENV_LOADED__'?'':(window._SESSION_AI_KEYS[provider]||'')).trim(); }
  const j = await api('/api/set-ai-key', {action:act, key:realVal, provider});
  if(j.ok){
    if(act==='apply'||act==='save'){
      if(realVal){
        window._SESSION_AI_KEYS[provider] = realVal;
        try{ localStorage.setItem(LSKEY_AI_MASK+'_'+provider, '__MASKED_APPLIED__'); }catch(e){}
        const inp=$('ai_pasteKey'); if(inp){ inp.value='••••••••••••••••'; inp.type='password'; inp.dataset.masked='1'; }
        const eye=$('ai_pasteKey_eye'); if(eye) eye.textContent='👁';
      }
    }
    if(act==='clear'){
      window._SESSION_AI_KEYS[provider]='';
      try{ localStorage.removeItem(LSKEY_AI_MASK+'_'+provider); }catch(e){}
      const inp=$('ai_pasteKey'); if(inp){ inp.value=''; inp.type='password'; inp.dataset.masked=''; }
      const eye=$('ai_pasteKey_eye'); if(eye) eye.textContent='👁';
    }
  }
  alert(j.ok? 'OK: '+(j.message||act) : 'Failed: '+(j.error||'unknown'));
  _refreshAiStatus();
}
// ============================================================
// ---- Floating chat widget + LLM action routing
// ============================================================
function _chatVisible(v){ const box=$('chatBox'); if(!box) return; box.style.display = v?'flex':'none'; }
function _appendChat(role, text){
  const root=$('chatMsgs'); if(!root) return;
  const wrap = document.createElement('div');
  wrap.style.cssText = (role==='user')
    ? 'align-self:flex-end;max-width:88%;background:var(--accent);color:#fff;border-radius:12px 12px 3px 12px;padding:9px 12px;font-size:12.5px;line-height:1.45'
    : 'align-self:flex-start;max-width:92%;background:var(--card);border:1px solid var(--line);border-radius:12px 12px 12px 3px;padding:10px 12px;font-size:12.5px;line-height:1.5';
  wrap.innerHTML = (role==='user'?'': '<b style="color:var(--accent)">🤖 </b>') + (text||'').replace(/\n/g,'<br>');
  root.appendChild(wrap);
  root.scrollTop = root.scrollHeight + 500;
}
function _aiSystemPrompt(){
  const flat = [];
  CATALOG.forEach(g=>{ const gn=catTitle(g); const gi=catIcon(g); (g.items||[]).forEach(it=>{
    flat.push({id:it.id, groupId:catIdOf(g), group:gi+' '+gn, title:it.title, desc:(it.desc||'').slice(0,180), cu:(it.cu_cost||''), status:(it.status||'')});
  });});
  return `You are Birdeye Data Copilot — a crypto data assistant inside the Birdeye Data Skills Hub (32 skills). Answer concisely in 2-4 lines.

CORE RULE — when user asks you to run, scan, analyze, or use any skill, YOU MUST output a single JSON block on its own line with no other text:
{"action":"run_skill","skillId":"<flat.id>","inputs":{...prefill dict...},"reason":"1 short sentence"}

Valid skillId values (pick exact match from catalog below):
${JSON.stringify(flat)}

User may say "trending list" → skillId=tl or tl_v3; "token DD / due diligence / audit address" → skillId=dd with address in inputs; "smart traders / smart wallets / top 9" → skillId=sm_wallets; "rug check" → skillId=rugcheck_risk_audit; "key management / API key" → skillId=key; "billing CU" → skillId=billing.

If inputs are missing (e.g. no token address for DD), respond conversationally asking user to provide the address. NEVER omit action when user explicitly requests a skill.`;
}
function _pickBestLLMKey(){
  // Priority: session RAM first, check env/file via ai-key-info async last-resort.
  for(const p of Object.keys(window._AI_PROV_META)){
    const k = window._SESSION_AI_KEYS[p] || '';
    if(k && k !== '__ENV_LOADED__') return {provider:p, key:k};
  }
  return null;
}
async function _callLLM(userText){
  const best = _pickBestLLMKey();
  if(!best) return {error:'NO_AI_KEY', msg:'No AI key in session. Paste in 🔑 Skill #28 → 🤖 AI BYO tab.'};
  const meta = window._AI_PROV_META[best.provider];
  const sys = _aiSystemPrompt();
  let body = null, url = meta.base + meta.path, headers = {}, method = 'POST';
  if(meta.kind === 'openai'){
    headers = {'Content-Type':'application/json', 'Authorization': meta.auth + best.key};
    body = {model: meta.model, temperature: 0.2, max_tokens: 700, messages:[
      {role:'system', content: sys}, {role:'user', content: userText}
    ]};
    url = meta.base + '/chat/completions';
  } else if(meta.kind === 'anthropic'){
    headers = {'Content-Type':'application/json', 'x-api-key': best.key, 'anthropic-version':'2023-06-01'};
    body = {model: meta.model, max_tokens: 700, temperature: 0.2, system: sys, messages:[{role:'user', content: userText}]};
    url = meta.base + '/messages';
  } else if(meta.kind === 'gemini'){
    headers = {'Content-Type':'application/json'};
    url = meta.base + '/models/'+meta.model+':generateContent?key='+encodeURIComponent(best.key);
    body = {generationConfig:{temperature:0.2,maxOutputTokens:700}, contents:[{role:'user', parts:[{text: sys+'\n\nUSER: '+userText}]}]};
  }
  try{
    const r = await fetch(url, {method, headers, body: body? JSON.stringify(body): undefined});
    const raw = await r.text();
    let obj; try{ obj = JSON.parse(raw); }catch(_){ obj = {__raw:raw}; }
    if(!r.ok) return {error:'HTTP '+r.status, msg:(obj?.error?.message || raw||'').slice(0,300)};
    let txt = '';
    if(meta.kind === 'openai') txt = obj?.choices?.[0]?.message?.content || '';
    else if(meta.kind === 'anthropic') txt = (obj?.content||[]).map(c=>c.text||'').join('') || '';
    else if(meta.kind === 'gemini') txt = obj?.candidates?.[0]?.content?.parts?.map(p=>p.text||'').join('') || '';
    return {text: txt, provider: best.provider, model: meta.model};
  }catch(e){ return {error:'NET', msg: String(e.message||e)}; }
}
function _parseAction(text){
  if(!text) return null;
  const patterns = [
    /```(?:json)?\s*([\s\S]*?)```/g,
    /\{[\s\S]*?"action"\s*:\s*"run_skill"[\s\S]*?\}/g,
    /\{[\s\S]*?"skillId"[\s\S]*?\}/g,
  ];
  for(const re of patterns){
    let m; re.lastIndex=0;
    while((m = re.exec(text)) !== null){
      const candidate = m[1] || m[0];
      try{ const j = JSON.parse(candidate.trim()); if(j && (j.action==='run_skill' || j.skillId)) return j; }catch(_){}
    }
  }
  return null;
}
function _routeAction(act){
  if(!act || !act.skillId) return false;
  // Find skill in catalog + drill to it
  let found = null, gFound = null;
  for(const g of CATALOG){
    for(const it of (g.items||[])){ if(it.id === act.skillId){ found=it; gFound=g; break; } }
    if(found) break;
  }
  if(!found){ _appendChat('bot', `⚠ Skill not found: ${act.skillId}. Valid IDs in catalog.`); return false; }
  const catId = catIdOf(gFound);
  if(window.STATE.mode !== 'drill'){ drillMode(catId); }
  window.STATE.activeCategory = catId;
  window.STATE.skill = act.skillId;
  // Breadcrumb
  const gT = catTitle(gFound); const gI = catIcon(gFound||{cat:''});
  const bc = $('breadcrumb');
  if(bc){ bc.style.display='';
    bc.innerHTML = `<span class="bcSeg" onclick="window.STATE.homeFilter='all';goHome();">🏠 Hub</span> <span class="sep">/</span> <span class="bcSeg" onclick="window.STATE.homeFilter='${catId}';window.STATE.mode='home';window.STATE.skill=null;renderHome();"><b>${gI} ${htmlEscape(gT)}</b></span> <span class="sep">/</span> ${htmlEscape(found.title)}`;
  }
  renderCatalog(); renderSkillCtrl();
  // Pre-fill inputs if any
  const inps = act.inputs || {};
  const inputNames = ['address','chain','limit','interval','source','sort_by','sortBy','platform'];
  for(const [k,v] of Object.entries(inps)){
    const id = (k==='address')?'dd_address':(k==='chain')?'dd_chain':(k==='limit')?'tl_limit':(k==='interval')?'tl_interval':(k==='source')?'tl_source':(k==='sort_by'||k==='sortBy')?'tl_sort':(k==='platform')?'tl_platform':null;
    if(!id) continue;
    const el = document.getElementById(id);
    if(el){ el.value = v; }
  }
  // Show prefill banner in both chat and control area
  const banner = $('chatPrefillBanner');
  if(banner){ banner.style.display=''; banner.innerHTML = `🤖 AI pre-filled · <b>${gI} ${htmlEscape(found.title)}</b> — click ▶ Run (NO auto-run). Reason: ${htmlEscape(act.reason||'AI matched skill')}`; }
  const bc2 = $('topBanner');
  if(!bc2){
    // Inject temporary banner at top of skill if missing
    const cp = $('controlPanel');
    if(cp){
      const topNode = document.createElement('div');
      topNode.style.cssText='margin-bottom:10px;padding:8px 10px;background:rgba(124,58,237,.1);border:1px solid rgba(124,58,237,.35);border-radius:10px;font-size:11.5px;color:var(--accent)';
      topNode.textContent = `🤖 AI pre-filled ${gI} ${found.title} — click ▶ Run (auto-run disabled).`;
      cp.insertBefore(topNode, cp.firstChild);
    }
  }
  _appendChat('bot', `✅ Routing to <b>${gI} ${found.title}</b>. Inputs: <code style="background:var(--tag);padding:1px 5px;border-radius:4px">${htmlEscape(JSON.stringify(inps))}</code><br>Click ▶ Run to execute (NO auto-run policy).`);
  return true;
}
async function _handleChatSend(){
  const inp = $('chatInput'); const send = $('chatSendBtn'); const text = (inp?.value||'').trim();
  if(!text) return;
  _appendChat('user', text);
  if(inp){ inp.value=''; }
  if(send){ send.disabled=true; send.style.opacity=.5; }
  try{
    const banner = $('chatPrefillBanner'); if(banner){ banner.style.display='none'; }
    const best = _pickBestLLMKey();
    if(!best){
      _appendChat('bot','🔑 <b>No AI key in session.</b><br>Go to <b>Skill #28 → 🤖 AI BYO tab</b> → Paste provider key → Apply session. Then retry.');
      return;
    }
    const r = await _callLLM(text);
    if(r.error){
      _appendChat('bot', `❌ ${r.error}: ${htmlEscape(r.msg||'')}`);
      return;
    }
    const reply = r.text || '';
    _appendChat('bot', reply);
    const act = _parseAction(reply);
    if(act) _routeAction(act);
  }finally{
    if(send){ send.disabled=false; send.style.opacity=''; }
  }
}
$('applySession')?.addEventListener('click', ()=>doKeyAction('apply', $('pasteKey').value));
$('savePersist')?.addEventListener('click', ()=>doKeyAction('save', $('pasteKey').value));
$('clearKey')?.addEventListener('click', ()=>doKeyAction('clear', ''));
$('hotReloadBtn').onclick = ()=>location.reload();
$('docsBtn').onclick = ()=>window.open('https://data.birdeye.so/docs/llms.txt', '_blank');

// ---------- Rendering ----------
function makeTrendRender(payload, sourceHint){
  const items = Array.isArray(payload?.rows)? payload.rows : (Array.isArray(payload?.items)?payload.items:[]);
  if(!items.length) return `<div class="render"><div>No rows (check key/limit/source).</div></div>`;
  const isV3 = sourceHint==='v3-list' || (payload && payload.source==='v3-list') ||
    items.some(x=> (x.trade_interval_count!=null && x.trade_interval_count!=='') || (x.tradeInterval!=null));
  const hasTrades = isV3;
  const hasHolders = isV3;
  const rowMap = (it)=>({
    rank: it.rank, address: it.address, symbol: it.symbol || '?',
    marketCap: it.marketCap ?? it.marketcap_usd ?? it.marketcap ?? it.market_cap,
    fdv: it.fdv ?? it.fdv_usd,
    liquidity: it.liquidity ?? it.liquidity_usd,
    price: it.price ?? it.price_usd,
    volInterval: it.volInterval ?? it.volume_interval_usd ?? it.volume ?? it.volume1hUSD ?? it.volume24hUSD,
    volChangePct: it.volChangePct ?? it.volume_interval_change_pct ?? it.volume_change_pct ?? it.volume1hChangePercent ?? it.volume24hChangePercent,
    priceChangePct: it.priceChangePct ?? it.price_interval_change_pct ?? it.price_change_pct ?? it.price1hChangePercent ?? it.price24hChangePercent,
    tradeInterval: it.tradeInterval ?? it.trade_interval_count ?? it.trade_count,
    holderCount: it.holderCount ?? it.holder_count ?? it.holders,
  });
  const cols = ['#','Symbol','MC','FDV','LIQ','Price','Vol','ΔV%','ΔP%'];
  if(hasTrades) cols.push('Trades');
  if(hasHolders) cols.push('Holders');
  const chain = (payload.chain||'').toUpperCase();
  const interval = payload.interval || '';
  return `<div class="render">
    <div>
      <div class="section-title">Trending · ${chain} · ${interval} · ${sourceHint||payload.source||''}</div>
      <div class="copyrow" style="margin-top:4px">
        ${items.slice(0,5).map(it0=>{const it=rowMap(it0);
          return `<button class="btn" data-sel='${JSON.stringify({addr:it.address,sym:it.symbol,chain:payload.chain||'sol',price:it.price,mc:it.marketCap})}'>${htmlEscape(it.symbol||'?')} · ${addrCut(it.address,4,4)}</button>`;
        }).join('')}
      </div>
    </div>
    <table class="t"><thead><tr>${cols.map(c=>`<th${c==='Symbol'?' class="sym"':''}>${c}</th>`).join('')}</tr></thead><tbody>
      ${items.map((it0,i)=>{
        const it = rowMap(it0);
        const dp=Number(it.priceChangePct); const dv=Number(it.volChangePct);
        return `<tr class="click" data-sel='${JSON.stringify({addr:it.address,sym:it.symbol,chain:payload.chain||'sol',price:it.price,mc:it.marketCap})}'>
          <td>${it.rank||i+1}</td>
          <td class="sym">${htmlEscape(it.symbol||'?')}<div class="subtle" style="font-size:11px">${addrCut(it.address||'')}</div></td>
          <td>${add$Label(it.marketCap)}</td>
          <td>${add$Label(it.fdv)}</td>
          <td>${add$Label(it.liquidity)}</td>
          <td>${add$Label(it.price)}</td>
          <td>${add$Label(it.volInterval)}</td>
          <td class="${dv>=0?'good':'bad'}">${fmtPctSigned(dv)}</td>
          <td class="${dp>=0?'good':'bad'}">${fmtPctSigned(dp)}</td>
          ${hasTrades?`<td>${it.tradeInterval==null||it.tradeInterval===''?'N/A':Number(it.tradeInterval).toLocaleString()}</td>`:''}
          ${hasHolders?`<td>${it.holderCount==null||it.holderCount===''?'N/A':Number(it.holderCount).toLocaleString()}</td>`:''}
        </tr>`;
      }).join('')}
    </tbody></table>
  </div>`;
}
// ---------- Smart Wallets render (Skill #9) ----------
function addrCut(a,pre=4,post=4){
  if(!a) return '';
  if(a.length<=pre+post+3) return a;
  return a.slice(0,pre)+'…'+a.slice(-post);
}
function fmtPctSigned(v){
  if(v==null||isNaN(v)) return 'N/A';
  const n=Number(v);
  const s=(n>=0?'+':'')+n.toFixed(1)+'%';
  return `<span class="${n>=0?'good':'bad'}">${s}</span>`;
}
function add$Label(v){
  if(v==null||v===''||isNaN(Number(v))) return '<span class="subtle">N/A</span>';
  const n=Number(v);
  const s=n<0; const a=Math.abs(n); const sg=s?'-':'';
  if(a>=1e9) return `${sg}$${(a/1e9).toFixed(2)}B`;
  if(a>=1e6) return `${sg}$${(a/1e6).toFixed(2)}M`;
  if(a>=1e3) return `${sg}$${(a/1e3).toFixed(1)}K`;
  return `${sg}$${a.toFixed(a<10?2:0)}`;
}
function makeSwRender(payload){
  const pass = Array.isArray(payload?.results_pass)? payload.results_pass : [];
  const drops = Array.isArray(payload?.results_drop_sample)? payload.results_drop_sample : [];
  const params = payload?.params || {};
  const w = params.weights || {winrate:40,pnl:25,rank:20,maxdd_inv:15};
  const sumW = (w.winrate||0)+(w.pnl||0)+(w.rank||0)+(w.maxdd_inv||0);
  if(!pass.length && !drops.length){
    return `<div class="render"><div class="warn">🧠 No wallets found — try lower pass score (current ≥ ${params.pass_min||70}), or change depth STANDARD/DEEP.</div>
      <pre class="out_body">${htmlEscape(JSON.stringify(payload?.invariants||{},null,2))}</pre></div>`;
  }
  const walletLink = (addr) => {
    if(!addr) return '';
    const chain = params.chain || 'sol';
    const beChain = ({sol:'solana',bsc:'bsc',base:'base',eth:'ethereum',arc:'arbitrum',robinhood:'robinhood'}[chain]) || chain;
    const url = `https://birdeye.so/account/${addr}?chain=${beChain}`;
    return `<a href="${url}" target="_blank" class="mini">🔎 view</a>`;
  };
  const scanSummary = `🧠 Skill #9 · <b>${params.depth_label||params.depth||''}</b> ${payload.cu_used_total||0} CU · chain=${params.chain||'sol'} · PASS ${payload.total_pass||pass.length}/${payload.total_wallets_scored||'?'} · DROP ${payload.total_drop||drops.length} · pass ≥ ${params.pass_min||70}/${sumW||100}pts · Weights WR${w.winrate}·PNL${w.pnl}·Rank${w.rank}·DDinv${w.maxdd_inv}`;
  const row = (r, idx, badge) => {
    const tags = Array.isArray(r.tags)? r.tags.slice(0,4).map(t=>`<span class="tag sm">${htmlEscape(t)}</span>`).join('') : '';
    const scorePct = r.score_max_total? Math.round(r.score_composite * 100 / r.score_max_total) : 0;
    const scColor = scorePct>=80?'good':(scorePct>=65?'warn':'bad');
    const nw = typeof r.networth_usd==='number' ? add$Label(r.networth_usd) : '<span class="subtle">N/A</span>';
    const perf = typeof r.perf_30d_pct==='number' ? fmtPctSigned(r.perf_30d_pct) : '<span class="subtle">N/A</span>';
    const wr = typeof r.win_rate_pct==='number'? `${r.win_rate_pct.toFixed(0)}%` : '—';
    const pnl = typeof r.pnl_multiple==='number'? `${r.pnl_multiple.toFixed(2)}×` : '—';
    const rk = typeof r.rank_sm_global==='number'? `#${r.rank_sm_global}` : '<span class="subtle">—</span>';
    const sp = r.score_parts||{};
    const parts = `<div class="subtle" style="font-size:10px;line-height:1.4">WR${sp.winrate||0}·PNL${sp.pnl||0}·RK${sp.sm_rank||0}·DD${sp.maxdd_inv||0}</div>`;
    const lastAgo = (()=>{
      if(!r.last_trade_ts) return '';
      const s=Math.max(1, Math.floor((Date.now()/1000) - Number(r.last_trade_ts)));
      if(s<60) return `${s}s`; if(s<3600) return `${Math.floor(s/60)}m`; if(s<86400) return `${Math.floor(s/3600)}h${Math.floor((s%3600)/60)}m`; return `${Math.floor(s/86400)}d`;
    })();
    const holdings = Array.isArray(r.holdings_top5) && r.holdings_top5.length ?
      `<div class="subtle" style="margin-top:4px;font-size:11px">Top holdings: `+r.holdings_top5.map(h=>{
        const v = typeof h.value_usd==='number' ? add$Label(h.value_usd) : '';
        const pc = typeof h.pct_change==='number' ? fmtPctSigned(h.pct_change) : '';
        return `<span style="margin-right:10px"><b>${htmlEscape(h.symbol||'?')}</b>${v?' '+v:''}${pc?' '+pc:''}</span>`;
      }).join('')+`</div>` : '';
    const drops = Array.isArray(r.drop_reasons) && r.drop_reasons.length ?
      `<div class="bad" style="margin-top:3px;font-size:11px">DROP: ${r.drop_reasons.map(dr=>htmlEscape(dr)).join(' · ')}</div>` : '';
    return `<tr class="click">
      <td style="vertical-align:top;padding:12px 8px;border-bottom:1px solid var(--line)">
        <div style="font-weight:700;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="sc">#${r.rank||idx+1}</span>
          <code>${addrCut(r.wallet,6,4)}</code>
          ${walletLink(r.wallet)}
          ${tags}
        </div>
        <div style="font-size:11px;color:var(--mute);margin-top:3px">
          ${typeof r.trade_count_30d==='number'?r.trade_count_30d.toLocaleString()+' trades 30d · ':''}
          ${typeof r.unique_tokens_30d==='number'?r.unique_tokens_30d+' tokens · ':''}
          last ${lastAgo||'?'} ago
        </div>
        ${holdings}
        ${drops}
      </td>
      <td style="vertical-align:top;text-align:right;font-weight:700">${nw}</td>
      <td style="vertical-align:top;text-align:right;font-weight:700">${perf}</td>
      <td style="vertical-align:top;text-align:right">${wr}</td>
      <td style="vertical-align:top;text-align:right">${pnl}</td>
      <td style="vertical-align:top;text-align:right">${rk}</td>
      <td style="vertical-align:top;text-align:right">
        <div style="font-weight:800" class="${scColor}">${r.score_composite}<span class="subtle">/${r.score_max_total||sumW}</span></div>
        ${parts}
      </td>
    </tr>`;
  };
  const passHtml = pass.length ?
    `<table class="t" style="margin-top:12px"><thead><tr>
      <th>Wallet</th><th style="text-align:right">💰 Net Worth</th><th style="text-align:right">📈 Perf 30d</th>
      <th style="text-align:right">🏆 WR</th><th style="text-align:right">× PNL</th>
      <th style="text-align:right">🎖 SM Rank</th><th style="text-align:right">Score</th>
    </tr></thead><tbody>${pass.slice(0,30).map((r,i)=>row(r,i,'')).join('')}</tbody></table>`
    : `<div class="warn">⚠ No PASS wallets — current pass min = ${params.pass_min||70}/${sumW||100}. Try lowering sliders pass min, or expand depth.</div>`;
  const dropsHtml = drops.length ?
    `<details style="margin-top:14px"><summary class="section-title">Drop reasons · sample ${Math.min(15,drops.length)} wallets (click to expand)</summary>
    <table class="t" style="margin-top:8px"><thead><tr>
      <th>Wallet (dropped)</th><th style="text-align:right">Net Worth</th><th style="text-align:right">Perf</th>
      <th style="text-align:right">WR</th><th style="text-align:right">Score</th>
    </tr></thead><tbody>${drops.slice(0,15).map((r,i)=>{
      const nw = typeof r.networth_usd==='number' ? add$Label(r.networth_usd) : '—';
      const perf = typeof r.perf_30d_pct==='number' ? fmtPctSigned(r.perf_30d_pct) : '—';
      const wr = typeof r.win_rate_pct==='number'? `${r.win_rate_pct.toFixed(0)}%` : '—';
      const tags = Array.isArray(r.tags)? r.tags.slice(0,3).map(t=>`<span class="tag sm">${htmlEscape(t)}</span>`).join('') : '';
      const drs = Array.isArray(r.drop_reasons)? r.drop_reasons.map(d=>htmlEscape(d)).join(' · ') : '';
      return `<tr>
        <td><div><code>${addrCut(r.wallet,6,4)}</code> ${walletLink(r.wallet)} ${tags}</div><div class="bad" style="font-size:11px">DROP: ${drs}</div></td>
        <td style="text-align:right">${nw}</td>
        <td style="text-align:right">${perf}</td>
        <td style="text-align:right">${wr}</td>
        <td style="text-align:right">${r.score_composite}/${r.score_max_total||sumW}</td>
      </tr>`;
    }).join('')}</tbody></table></details>` : '';
  return `<div class="render">
    <div class="section-title" style="font-size:15px">${scanSummary}</div>
    ${passHtml}
    ${dropsHtml}
    ${payload.invariants?.gaps?.length? `<div style="margin-top:10px;font-size:12px" class="warn">⚠ Pipeline gaps: ${payload.invariants.gaps.map(g=>htmlEscape(g)).join(' · ')}</div>`:''}
  </div>`;
}
// ---------- Skill #17b · RugCheck Audit — same UI as rugcheck.xyz ----------
function tierBadge(text, tier){
  const cls = { high:'bad', warn:'warn', caution:'warn', low:'good', safe:'good', danger:'bad' }[tier||'low'] || 'good';
  return `<span class="chip ${cls}" style="font-weight:700;padding:2px 8px;font-size:11px">${htmlEscape(text||'')}</span>`;
}
function usdFmt(v, digits=0){
  if(v === null || v === undefined || v === '') return '—';
  const n = Number(v)||0;
  const abs = Math.abs(n);
  const sign = n<0 ? '-' : '';
  if(abs >= 1e9) return sign+'$'+(abs/1e9).toFixed(2)+'B';
  if(abs >= 1e6) return sign+'$'+(abs/1e6).toFixed(2)+'M';
  if(abs >= 1e3) return sign+'$'+(abs/1e3).toFixed(1)+'K';
  return sign+'$'+abs.toFixed(digits||0);
}
function pctFmt(v, digits=2){ if(v===null||v===undefined||v==='') return '—'; const n = Number(v)||0; return (n>=0?'+':'')+(n.toFixed(digits))+'%'; }
function shortAddr(a){
  if(!a) return '';
  const s = String(a);
  return s.length > 10 ? (s.slice(0,4)+'…'+s.slice(-4)) : s;
}
// compute 7 risk cards severity + badges
function computeRiskCards(payload){
  const sec = payload.security || {};
  const ovd = payload.overview || payload.token_security_data || payload.ovd || {};
  const rd  = payload.rugcheck || payload.rug_data || payload.rug || {};
  // Top-level canonical fields from fresh CLI raw-json payload (birdeye_cli rugcheck-audit output)
  const tl  = payload || {};
  // T10 %
  const top10 = Number(rd.holders_top10_pct ?? sec.top10_holder_pct ?? sec.topHoldersPct ?? sec.top10_pct ?? (sec.raw && sec.raw.top10UserPercent*100) ?? 0) || 0;
  const devPct = Number(rd.holder_creator_pct ?? sec.dev_holding_pct ?? sec.devPct ?? sec.developerPct ?? (sec.raw && sec.raw.creatorPercentage*100) ?? 0) || 0;
  const liqUsd = Number(rd.liq_current_usd ?? tl.liquidity_usd ?? ovd.liquidity ?? ovd.liquidityUsd ?? tl.liquidity ?? 0) || 0;
  const mcapUsd = Number(tl.marketcap_usd ?? ovd.marketCap ?? ovd.marketcap ?? ovd.mcap ?? tl.market_cap ?? tl.mcap ?? 0) || 0;
  const fdvUsd  = Number(tl.fdv_usd ?? ovd.fdv ?? tl.fdv ?? 0) || 0;
  const price   = Number(tl.price_usd ?? ovd.price ?? ovd.priceUsd ?? tl.price ?? 0) || 0;
  const holders = Number(tl.holder_count ?? ovd.holderCount ?? ovd.holders ?? sec.holderCount ?? tl.holders ?? 0) || 0;
  const lpProviders = Number(rd.lp_providers_count ?? 1);
  const lpUnlocked = Number(rd.lp_unlocked_pct ?? (sec.lpLocked ? (100-Number(sec.lpLockedPct||0)) : 100));
  const feeEnabled = (rd.fee_enabled === true);
  const metaMutable = (rd.metadata_mutable === true);
  const mintAuth = (rd.mint_authority_enabled === true);
  const honey = !!sec.isHoneyPot || !!sec.honeypot;
  const per = mcapUsd > 0 && holders > 0 ? (mcapUsd / holders) : 0;
  const liqMc = mcapUsd > 0 ? (liqUsd / mcapUsd * 100.0) : 0;
  const card = (id, title, desc, tier, value) => ({id, title, desc, tier, value});
  const tierUnlocked = lpUnlocked>=90?'danger':(lpUnlocked>=60?'high':(lpUnlocked>=40?'warn':'safe'));
  const tierT10 = top10>=80?'danger':(top10>=60?'high':(top10>=40?'warn':(top10>=20?'caution':'safe')));
  let tierLiq = 'safe';
  if(liqUsd < 500) tierLiq = 'danger';
  else if(liqUsd < 5000) tierLiq = 'high';
  else if(liqUsd < 25000) tierLiq = 'warn';
  const tierPer = per > 100000 ? 'warn' : (per>20000?'caution':'safe');
  const tierLpProv = lpProviders <= 2 ? 'danger' : (lpProviders<=5?'warn':'safe');
  const tierFee = feeEnabled ? 'warn' : 'safe';
  const tierMint = mintAuth ? 'danger' : (metaMutable?'warn':'safe');
  const score7 = [
    card('lp-unlock','LP Unlocked','% of liquidity not locked by creator/team', tierUnlocked, lpUnlocked.toFixed(1)+' %'),
    card('top10','Top 10 Holders','Holder concentration (top 10 wallets ownership % = rug ease)', tierT10, top10.toFixed(1)+' %'),
    card('low-liq','Low Liquidity','Minimum liquidity to exit without huge slippage ($ ≥25K healthy)', tierLiq, usdFmt(liqUsd,2)+'  ('+liqMc.toFixed(1)+'% of MC)'),
    card('per-holder','MC / Wallet avg','Extremely high per-wallet → paper wealth no holders trap', tierPer, usdFmt(per,0)),
    card('lp-prov','LP Provider count','≤2 = centralized rug control (one wallet owns entire pool)', tierLpProv, String(lpProviders)+' wallets'),
    card('fee','Fee / Tax Config','Token has transfer fee → rake on buys/sells exit', tierFee, (feeEnabled?'⚠ ENABLED':'Not enabled')),
    card('auth','Mint / Freeze / Meta','Creator can mint infinite supply OR mutate metadata rug swap', tierMint, (mintAuth?'🔴 MINTABLE!': (metaMutable?'metadata mutable':'Auth renounced ✓'))),
  ];
  return {
    cards: score7,
    summary: {
      totalRisks: score7.filter(c=>['danger','high','warn'].includes(c.tier)).length,
      hasHoneypot: honey,
      mintAuth, metaMutable, feeEnabled,
      devPct, top10, liqUsd, mcapUsd, fdv: fdvUsd, price, holders,
      lpProviders, lpUnlocked,
    }
  };
}
function makeRugCheckRender(payload, jobj){
  const ovd = payload.overview || payload.token_security_data || payload.ovd || {};
  const sec = payload.security || {};
  // NOTE: Fresh CLI rugcheck-audit puts RC extras under payload.rugcheck; legacy code used rug_data. Support BOTH.
  const rd = payload.rugcheck || payload.rug_data || payload.rug || {};
  const params = payload.params || {};
  // Top-level canonical fields (from CLI rugcheck-audit raw-json output: schemaVersion==1)
  const tl = payload || {};
  const risk7 = computeRiskCards(payload);
  const s = risk7.summary;
  const totalRisks = s.totalRisks;
  const riskTier = s.hasHoneypot ? 'DANGER' : (totalRisks>=5?'HIGH':(totalRisks>=3?'ELEVATED':(totalRisks>=1?'CAUTION':'LOW')));
  const riskCls = {'DANGER':'bad','HIGH':'bad','ELEVATED':'warn','CAUTION':'warn','LOW':'good'}[riskTier]||'good';
  const price = Number(s.price || tl.price_usd || ovd.price || ovd.priceUsd || payload.price || 0) || 0;
  const addr = params.address || ovd.address || payload.address || tl.address || '';
  const chain = (params.chain || payload.chain || tl.chain || 'sol').toLowerCase();
  const sym = ovd.symbol || ovd.symbol_token || tl.symbol || payload.symbol || 'TOKEN';
  const name = ovd.name || tl.name || payload.name || '';
  const logo = ovd.logoURI || ovd.logo || tl.logo || payload.logo || '';
  // Top 10 holders array (prefer rugcheck block; fallback top10 slice)
  const holdersT10 = (rd.holders_raw || []).slice(0, 10);
  const liqWin = rd.liq_window || '24h';
  const liqMin = rd.liq_min_window_usd, liqMax = rd.liq_max_window_usd, liqDD = rd.liq_drawdown_window_pct;
  const liqDDTier = (Number(liqDD)>=70)?'danger':(Number(liqDD)>=40?'high':(Number(liqDD)>=20?'warn':(Number(liqDD)>=10?'caution':'safe')));
  const cohorts = rd.cohort_breakdown || [];
  const hasInsiders = cohorts.length>0 || Object.keys(rd.insider_cohorts||{}).length>0;
  // -----------------------------------------------------------
  // 6 Cohort Summary chips: Insider/Sniper/Bundle/Dev/SmartMoney/Whale
  // (user request: "5 data trên top section cạnh top 10%")
  // Normalize EARLY so top chips + Insiders tab share the same array.
  // -----------------------------------------------------------
  function _normalizeCohorts() {
    // Primary: rd.cohort_breakdown (array of {name, pct, holder_count, tier})
    if (Array.isArray(cohorts) && cohorts.length) {
      return cohorts.map(c => {
        const name = (c.name || c.tag || c.label || 'Unknown').toString().trim();
        let pct = Number(c.pct != null ? c.pct : (c.percent != null ? c.percent : c.hold_pct));
        if (isNaN(pct)) pct = 0;
        // Tight 0..1 vs 0..100 guard. Holder-profile percent_of_supply is 0..100.
        // Only values <= 0.005 are treated as legacy true 0..1 ratios (multiply by 100).
        // Percentages like 0.903 (0.9%) are passed through — NEVER scale to 90.3%.
        if (pct > 0 && pct <= 0.005) pct = pct * 100;
        const count = c.count != null ? c.count : c.holder_count;
        const countOk = count != null && !isNaN(Number(count));
        const buy$ = c.buy_volume_usd != null ? c.buy_volume_usd : (c.buyVolUsd || c.buy_usd);
        const sell$ = c.sell_volume_usd != null ? c.sell_volume_usd : (c.sellVolUsd || c.sell_usd);
        const avgB = c.avg_buy_price != null ? c.avg_buy_price : c.avgBuyPrice;
        const pnl = c.pnl != null ? c.pnl : c.profitLossUsd;
        const tier = c.tier || (pct >= 15 ? 'high' : (pct >= 5 ? 'warn' : (pct >= 1 ? 'caution' : 'low')));
        return {name, pct, count: countOk ? Number(count) : null, tier, buy$, sell$, avgB, pnl};
      }).filter(c => (Number(c.pct) > 0) || (c.count != null && Number(c.count) > 0));
    }
    // Fallback: rd.insider_cohorts dict name->pct
    const ic = rd.insider_cohorts || {};
    if (ic && typeof ic === 'object' && Object.keys(ic).length) {
      const _title = s => {
        let r = String(s || '').replace(/([a-z])([A-Z])/g, '$1 $2');
        r = r.replace(/^[_\s]+|[\s_]+$/g, '').replace(/(^|[\s_])([a-z])/g, (_, l, c) => l + c.toUpperCase());
        r = r.replace(/[_]+/g, ' ').replace(/Smart ?Money/gi, 'SmartMoney').replace('Smartmoney', 'SmartMoney');
        return r;
      };
      return Object.entries(ic).map(([n, p]) => {
        let pct = Number(p || 0);
        // Same tightened guard — <= 0.005 as ratio 0..1 only; never scale 0.9% → 90%.
        if (pct > 0 && pct <= 0.005) pct *= 100;
        return {name: _title(n), pct, count: null, tier: pct >= 15 ? 'high' : (pct >= 5 ? 'warn' : (pct >= 1 ? 'caution' : 'low'))};
      }).filter(c => Number(c.pct) > 0);
    }
    return [];
  }
  const cleanCohorts = _normalizeCohorts();
  const cohortChipsSummary = (() => {
    if (!cleanCohorts.length) return '';
    const DISPLAY_ORDER = ['Insider', 'Sniper', 'Bundle', 'Bundler', 'Dev', 'Developer', 'SmartMoney', 'Smart Trader', 'Whale', 'Kol', 'Bot', 'Airdrop'];
    const sorted = cleanCohorts.slice().sort((a,b) => {
      const ai = DISPLAY_ORDER.indexOf(a.name), bi = DISPLAY_ORDER.indexOf(b.name);
      if (ai>=0 && bi>=0) return ai-bi;
      if (ai>=0) return -1; if (bi>=0) return 1;
      return (Number(b.pct)||0) - (Number(a.pct)||0);
    });
    return sorted.slice(0, 8).map(c => {
      const countStr = (c.count != null && !isNaN(Number(c.count))) ? ' · ' + Number(c.count).toLocaleString() : '';
      const pctVal = Number(c.pct) || 0;
      const tier = c.tier;
      const cls = {high:'bad', danger:'bad', warn:'warn', caution:'warn', low:'good', safe:'good'}[tier] || 'good';
      return `<span class="chip ${cls}" title="${htmlEscape(`${c.name}: ${pctVal.toFixed(2)}% of supply${countStr} wallets`)}" style="padding:3px 10px;font-size:11.5px;font-weight:800">${htmlEscape(c.name)} <b style="margin-left:4px">${pctVal.toFixed(2)}%</b>${countStr?`<span class="subtle" style="font-weight:500;margin-left:4px">${htmlEscape(countStr)}</span>`:''}</span>`;
    }).join('');
  })();
  // holders table top N = min(holders_raw.length, 20 default user param)
  const holders = rd.holders_raw || [];
  const cardsHtml = risk7.cards.map(c=>{
    return `<div style="border:1px solid var(--line);border-radius:10px;background:var(--card-bg);padding:12px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span style="font-weight:700;font-size:13px">${htmlEscape(c.title)}</span>
        <div style="flex:1"></div>
        ${tierBadge(c.value, c.tier)}
      </div>
      <div class="subtle" style="font-size:11px">${htmlEscape(c.desc||'')}</div>
    </div>`;
  }).join('');
  // ----- Money Flow table: net flow per window MUST be resolved via money_flow_rows (mf_map)
  //       Python buy_sell_rows tuple = 9-elements [i, vol$, buy$, sell$, bRatio, buys, sells, trRatio, wallets]
  //       Destructuring a phantom "net" 10th element yields undefined → displayed garbage "+—".
  //       Also add $0 explicit fallback for bPct/trPct when ratio is null instead of Number(0).
  const mfMap = {};
  (payload.money_flow_rows||[]).forEach(([iv,mf])=>{ mfMap[String(iv)] = mf; });
  const marketTableRows = (payload.buy_sell_rows||[]).map((row,idx)=>{
    const [iv, vol$, buy$, sell$, bPctRaw, buys, sells, trPctRaw, wals] = row;
    const net = mfMap[String(iv)];
    const bPctN = (bPctRaw==null||isNaN(Number(bPctRaw)))?null:Number(bPctRaw)*100;
    const trPctN = (trPctRaw==null||isNaN(Number(trPctRaw)))?null:Number(trPctRaw)*100;
    const bPctStr = bPctN===null? '—' : (bPctN.toFixed(0)+'%');
    const trPctStr = trPctN===null? '—' : (trPctN.toFixed(0)+'%');
    const buysS = (buys==null||isNaN(Number(buys)))? '—' : Number(buys).toLocaleString();
    const sellsS = (sells==null||isNaN(Number(sells)))? '—' : Number(sells).toLocaleString();
    const walsS = (wals==null||isNaN(Number(wals)))? '—' : Number(wals).toLocaleString();
    const netN = (net==null||isNaN(Number(net)))? null : Number(net);
    let netCell = '—';
    let netCls = '';
    if (netN !== null) {
      const av = Math.abs(netN);
      const sig = netN >= 0 ? '+' : '-';
      let body;
      if (av >= 1e9) body = '$'+(av/1e9).toFixed(1)+'B';
      else if (av >= 1e6) body = '$'+(av/1e6).toFixed(1)+'M';
      else if (av >= 1e3) body = '$'+(av/1e3).toFixed(1)+'K';
      else if (av >= 1) body = '$'+av.toFixed(2);
      else body = '$'+av.toFixed(4);
      netCell = sig + body;
      netCls = (netN >= 0) ? 'good' : 'bad';
    }
    return `<tr>
      <td style="font-weight:600">${htmlEscape(String(iv))}</td>
      <td>${usdFmt(vol$)}</td>
      <td style="color:var(--good)">${usdFmt(buy$)}</td>
      <td style="color:var(--bad)">${usdFmt(sell$)}</td>
      <td>${bPctStr}</td>
      <td>${buysS}</td>
      <td>${sellsS}</td>
      <td>${trPctStr}</td>
      <td>${walsS}</td>
      <td style="color:var(--${netCls||'mute'});font-weight:600">${netCell}</td>
    </tr>`;
  }).join('');
  const priceChanges = (payload.price_changes||[]).map(([iv,pct])=>{
    const tier = Number(pct)<-10?'danger':(Number(pct)<-3?'warn':(Number(pct)>3?'safe':'low'));
    return `<span style="display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;border:1px solid var(--line);background:var(--card-bg);font-size:12px;margin-right:8px;margin-bottom:6px">
      <span style="font-weight:600">${htmlEscape(iv)}</span>
      <span class="${tier==='safe'?'good':(tier==='danger'?'bad':'warn')}" style="font-weight:700">${pctFmt(pct,1)}</span>
    </span>`;
  }).join('');
  // Holder rows: tolerate null usd_value (calc via amount*price when price avail),
  //               tolerate null/whitespace amount_raw (use ui_amount/numeric amount if exists).
  const priceH = Number(s.price || tl.price_usd || ovd.price || ovd.priceUsd || payload.price || NaN);
  const holdersRowsHtml = holders.map(h=>{
    const labelColor = h.label && (/(creator|deploy)/i.test(h.label)) ? 'bad'
                     : h.label && (/(pool|amm|lp|meteora|raydium|orca|dex|authority)/i.test(h.label)) ? 'good'
                     : (h.tags||[]).length ? 'warn' : 'mute';
    let usdDisp = '—';
    if (h.usd_value!=null && !isNaN(Number(h.usd_value))) {
      usdDisp = usdFmt(Number(h.usd_value), 0);
    } else if (!isNaN(priceH) && priceH > 0 && h.amount_tokens!=null && !isNaN(Number(h.amount_tokens))) {
      usdDisp = usdFmt(Number(h.amount_tokens) * priceH, 0);
    } else if (!isNaN(priceH) && priceH > 0 && h.ui_amount!=null && !isNaN(Number(h.ui_amount))) {
      usdDisp = usdFmt(Number(h.ui_amount) * priceH, 0);
    }
    let amtStr = (h.amount_raw||'').toString().trim();
    if (!amtStr || amtStr==='null' || amtStr==='undefined') {
      if (h.ui_amount!=null && !isNaN(Number(h.ui_amount))) {
        const u = Number(h.ui_amount);
        amtStr = (u >= 1e9? (u/1e9).toFixed(2)+'B' : (u>=1e6?(u/1e6).toFixed(2)+'M' : (u>=1e3?u.toLocaleString(undefined,{maximumFractionDigits:2}):u.toFixed(4))));
      } else if (h.amount_tokens!=null && !isNaN(Number(h.amount_tokens))) {
        const u = Number(h.amount_tokens);
        amtStr = (u >= 1e9? (u/1e9).toFixed(2)+'B' : (u>=1e6?(u/1e6).toFixed(2)+'M' : (u>=1e3?u.toLocaleString(undefined,{maximumFractionDigits:2}):u.toFixed(4))));
      } else {
        amtStr = '—';
      }
    }
    return `<tr>
      <td style="font-weight:700;color:var(--mute)">${Number(h.rank||0)}</td>
      <td>${h.label ? `<span class="chip ${labelColor}" style="font-weight:600;font-size:11px;padding:2px 8px">${htmlEscape(h.label)}</span>` : (h.tags?.length?`<span class="chip warn" style="font-weight:600;font-size:11px;padding:2px 8px">${htmlEscape(h.tags.join(' · '))}</span>`:'<span class="subtle">—</span>')}</td>
      <td style="font-family:monospace;font-size:12px">${h.owner ? `<a href="https://birdeye.so/account/${encodeURIComponent(h.owner)}?chain=${encodeURIComponent(chain==='arc'?'arbitrum':chain)}" target="_blank" rel="noreferrer">${htmlEscape(h.owner_short||shortAddr(h.owner))}</a>`:'—'}</td>
      <td style="font-weight:700">${h.pct!==null&&h.pct!==undefined&&!isNaN(Number(h.pct))?Number(h.pct).toFixed(2)+' %':'—'}</td>
      <td style="font-weight:600">${usdDisp}</td>
      <td class="subtle" style="font-family:monospace;font-size:11.5px;max-width:180px;overflow:hidden;text-overflow:ellipsis">${htmlEscape(String(amtStr).slice(0,20))}</td>
    </tr>`;
  }).join('');
  const totalHolders = Number(payload.holder_count || s.holders || rd.holders_top10_pct != null ? (rd.holders_raw && rd.holders_raw.length && s.holders) || s.holders || 0 : 0) || Number(s.holders||0);
  const cohortHtml = cleanCohorts.length ? cleanCohorts.map(c => {
    const pctVal = Number(c.pct) || 0;
    let countStr = '— count N/A';
    if (c.count != null && !isNaN(Number(c.count))) {
      countStr = Number(c.count).toLocaleString() + ' wallets';
    } else if (totalHolders > 0 && pctVal > 0) {
      const est = Math.max(1, Math.round(totalHolders * pctVal / 100));
      countStr = '≈ ' + est.toLocaleString() + ' wallets (est.)';
    }
    const extras = [];
    if (c.buy$ != null && !isNaN(Number(c.buy$))) extras.push('BUY ' + _fmtUSD(c.buy$, 1));
    if (c.sell$ != null && !isNaN(Number(c.sell$))) extras.push('SELL ' + _fmtUSD(c.sell$, 1));
    if (c.avgB != null && !isNaN(Number(c.avgB))) extras.push('AVG ' + _fmtUSD(c.avgB, 2));
    if (c.pnl != null && !isNaN(Number(c.pnl))) {
      const pn = Number(c.pnl);
      const sign = pn >= 0 ? '+' : '-';
      extras.push('PNL ' + sign + _fmtUSD(Math.abs(pn), 1));
    }
    const exStr = extras.length ? `<div style="font-size:10.5px;color:var(--mute);margin-top:2px">${extras.join(' · ')}</div>` : '';
    return `<div style="padding:10px 12px;border-radius:10px;background:var(--card-bg);border:1px solid var(--line);display:flex;align-items:center;gap:10px">
      <div style="flex:1;min-width:0">
        <div style="font-weight:800;font-size:13px">${htmlEscape(c.name)}</div>
        <div style="font-size:11px;color:var(--mute);font-weight:600;margin-top:2px">${countStr}</div>
        ${exStr}
      </div>
      ${tierBadge((isNaN(pctVal)?'0':pctVal.toFixed(2))+' %', c.tier)}
    </div>`;
  }).join('') : '<div class="subtle">No cohort breakdown returned by API (try raw-json format fallback / or endpoint path mismatch Birdeye header)</div>';
  const lockersHtml = `
    <div class="kv"><span>LP Lock Verified (on-chain)</span><span>${s.lpUnlocked<=5?'<span class="chip good">✅ Proof</span>':'<span class="chip bad">❌ NO proof</span>'}</span></div>
    <div class="kv"><span>LP Unlocked %</span><span>${tierBadge(s.lpUnlocked.toFixed(1)+' %', s.lpUnlocked>=90?'danger':(s.lpUnlocked>=60?'high':'safe'))}</span></div>
    <div class="kv"><span>LP Provider wallets count</span><span>${tierBadge(String(s.lpProviders)+' wallets', s.lpProviders<=2?'danger':'safe')}</span></div>
    <div class="kv"><span>LP ${liqWin} Drain (peak→cur DD)</span><span>${tierBadge((liqDD===undefined||liqDD===null)?'—':('−'+Number(liqDD).toFixed(1)+' %'), liqDDTier)}</span></div>
    <div class="kv"><span>Fee Configured</span><span>${s.feeEnabled?'<span class="chip warn">⚠ YES rake</span>':'<span class="chip good">No transfer tax</span>'}</span></div>
    <div class="kv"><span>Metadata Mutable</span><span>${s.metaMutable?'<span class="chip warn">⚠ Mutable</span>':'<span class="chip good">Immutable</span>'}</span></div>
    <div class="kv"><span>Mint / Freeze Auth</span><span>${s.mintAuth?'<span class="chip bad">🔴 MINTABLE! unlimited rug</span>':'<span class="chip good">✅ Renounced</span>'}</span></div>
  `;
  const score = payload.scores || {};
  const scoreLine = `<div style="display:flex;gap:10px;align-items:stretch;margin-top:12px;flex-wrap:wrap">
    ${['sec','smkt','act','vol','final'].map(k=>{
      const val = Number(score[k] ?? -1);
      if(val<0) return '';
      const pct = val/10*100;
      const cls = pct>=80?'good':(pct>=65?'warn':'bad');
      const label = ({sec:'SEC', smkt:'SMKT', act:'ACT', vol:'VOL', final:'FINAL'})[k];
      const w = k==='final' ? '130px' : '110px';
      return `<div style="flex:0 0 ${w};border:1px solid var(--line);border-radius:10px;background:var(--card-bg);padding:10px 8px;text-align:center">
        <div style="font-size:18px;font-weight:800" class="${cls}">${val.toFixed(1)}<span style="font-size:11px;color:var(--mute);font-weight:500">/10</span></div>
        <div style="font-size:11px;color:var(--mute);font-weight:700;letter-spacing:.3px;margin-top:3px">${label}</div>
      </div>`;
    }).filter(Boolean).join('')}
  </div>`;
  const verdict = payload.verdict || '';
  const verdictCls = /BUY|STRONG|GOOD|SAFE|A/i.test(verdict)?'good':(/HOLD|WATCH|NEUTRAL/i.test(verdict)?'warn':'bad');
  return `<div class="render" id="rug_root" style="padding:4px 0 0">
    <style>
      #rug_root .tabber{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:6px 0 10px;flex-wrap:wrap;position:sticky;top:0;background:var(--bg);z-index:5;padding-top:4px}
      #rug_root .tabber button{padding:7px 13px;border-radius:8px 8px 0 0;background:transparent;color:var(--mute);border:0;border-bottom:2px solid transparent;font-weight:700;font-size:12.5px;cursor:pointer;white-space:nowrap}
      #rug_root .tabber button.on{background:var(--card-bg);border:1px solid var(--line);border-bottom-color:transparent;color:var(--text)}
      #rug_root .rc-tab{display:block;margin-bottom:18px;padding:12px 0 4px;border-top:1px dashed transparent;scroll-margin-top:52px;transition:border-color .2s}
      #rug_root .rc-tab.on{border-top-color:transparent;border-left:3px solid var(--grad-a);padding-left:10px;margin-left:-10px;background:linear-gradient(90deg, rgba(80,120,255,.06) 0%, transparent 60%)}
      #rug_root .rc-hero{display:flex;align-items:center;gap:14px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg, var(--card-bg) 0%, var(--ctrl-bg) 100%);margin-bottom:10px}
      #rug_root .rc-hero h1{margin:0;font-size:16px;font-weight:800;display:flex;align-items:center;gap:10px}
      #rug_root .rc-hero .mkt{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--mute)}
      #rug_root .rc-hero .mkt span b{color:var(--text);font-weight:700}
      #rug_root table.rc-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
      #rug_root table.rc-tbl th,#rug_root table.rc-tbl td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
      #rug_root table.rc-tbl th{color:var(--mute);font-weight:700;font-size:11px;background:var(--card-bg);letter-spacing:.25px;text-transform:uppercase;border-top:1px solid var(--line)}
      #rug_root .cards{display:grid;grid-template-columns:repeat(auto-fill, minmax(240px,1fr));gap:10px}
      #rug_root .kv{display:flex;justify-content:space-between;padding:8px 12px;border-bottom:1px dashed var(--line);font-size:13px;color:var(--text)}
      #rug_root .kv span:last-child{font-weight:700;text-align:right}
    </style>
    <div class="rc-hero">
      ${logo?`<img src="${htmlEscape(logo)}" alt="" style="width:44px;height:44px;border-radius:50%;background:var(--card-bg);border:1px solid var(--line);flex:0 0 44px">`:''}
      <div style="flex:1;min-width:0">
        <h1><span>${htmlEscape(sym)} ${name?'<span class="subtle" style="font-weight:500">('+htmlEscape(name)+')</span>':''}</span><span class="chip ${riskCls}" style="font-weight:800;font-size:12px;padding:4px 10px">RISK ${riskTier} · ${totalRisks}/7 risks</span>${s.hasHoneypot?'<span class="chip bad" style="font-weight:800">🔴 HONEYPOT</span>':''}</h1>
        <div class="subtle" style="font-size:11.5px;margin:4px 0 6px;font-family:monospace">
          <a href="https://birdeye.so/token/${encodeURIComponent(addr)}?chain=${encodeURIComponent(chain==='arc'?'arbitrum':chain)}" target="_blank" rel="noreferrer">${htmlEscape(addr)}</a> · Chain <b>${htmlEscape(chain.toUpperCase())}</b>
        </div>
        <div class="mkt">
          <span><b>${usdFmt(price,6)}</b> price</span>
          <span><b>MC ${usdFmt(s.mcapUsd,2)}</b></span>
          <span><b>FDV ${usdFmt(s.fdv,2)}</b></span>
          <span><b>LIQ ${usdFmt(s.liqUsd,2)}</b></span>
          <span><b>${s.holders.toLocaleString()}</b> Holders</span>
        </div>
        ${priceChanges?`<div style="margin-top:8px">${priceChanges}</div>`:''}
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px">
      ${tierBadge('Dev '+s.devPct.toFixed(2)+'%', s.devPct>=15?'high':(s.devPct>=5?'warn':'safe'))}
      ${tierBadge('Top10 '+s.top10.toFixed(2)+'%', s.top10>=60?'danger':(s.top10>=40?'warn':'safe'))}
      ${(rd.holders_raw&&rd.holders_raw.length)?`<span class="chip cu">Top holders list returned: ${String(rd.holders_raw.length)} rows</span>`:`<span class="chip warn">Holder list fallback aggregate (--rug-show-holders=NO / or API no rows returned)</span>`}
      ${cohortChipsSummary || ''}
      <div style="flex:1"></div>
      <div class="subtle" style="font-size:11.5px">CU <b>${payload.cu_used_total||(jobj&&jobj.cu_total)||'?'}</b> · ${(function(){
  const raw = payload.cu_breakdown;
  if (raw == null || raw === undefined) return '';
  if (typeof raw === 'string') {
    return raw.replace(/\s*=\s*\d+\s*CU\s*$/,'').replace(/\s+/g,' ').trim();
  }
  if (Array.isArray(raw)) {
    if (raw.every(x=> typeof x === 'string')) return raw.join(' · ');
    return raw.map(x => typeof x==='string'?x:(x?x.name+'='+x.pct:'')).join(' · ');
  }
  if (typeof raw === 'object') {
    const arr = Object.entries(raw).map(([k,v])=>k+'='+(v==null?'?':v));
    const rug = arr.filter(x=>/rug_|_extra|hold|advsec|liq|sm_|list|hist|refund/.test(x.split('=')[0]));
    return (rug.length?rug:arr).join(' · ');
  }
  return String(raw);
})()}</div>
    </div>
    <div class="tabber" role="tablist">
      <button role="tab" class="on" data-rc-tab="ovr">Overview · ${totalRisks} risks</button>
      <button role="tab" data-rc-tab="mkt">Markets · Buy/Sell Money Flow</button>
      <button role="tab" data-rc-tab="ins">Insiders · Cohort Breakdown ${hasInsiders?'('+(cohorts.length||Object.keys(rd.insider_cohorts||{}).length)+')':''}</button>
      <button role="tab" data-rc-tab="hld">Holders · ${s.holders.toLocaleString()} (Top ${holders.length||0} rows)</button>
      <button role="tab" data-rc-tab="lp">Lockers & LP</button>
    </div>
    <div id="rc-section-ovr" class="rc-tab on">
      <div class="cards">${cardsHtml}</div>
      <div style="margin-top:16px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--card-bg)">
        <div style="font-weight:800;margin-bottom:8px">💧 Liquidity History · Window <b>${liqWin}</b> <span class="subtle" style="font-weight:500;font-size:11px">(×1 API call ~20 CU)</span></div>
        <div style="display:flex;gap:14px;flex-wrap:wrap">
          <div><span class="subtle" style="font-size:11px">CURRENT</span><div style="font-size:15px;font-weight:800;margin-top:2px">${usdFmt(s.liqUsd,2)}</div></div>
          <div><span class="subtle" style="font-size:11px">${liqWin} MIN</span><div style="font-size:15px;font-weight:800;margin-top:2px;color:var(--bad)">${liqMin===undefined?'—':usdFmt(liqMin,2)}</div></div>
          <div><span class="subtle" style="font-size:11px">${liqWin} MAX</span><div style="font-size:15px;font-weight:800;margin-top:2px;color:var(--good)">${liqMax===undefined?'—':usdFmt(liqMax,2)}</div></div>
          <div><span class="subtle" style="font-size:11px">DRAWDOWN vs peak</span><div style="font-size:15px;font-weight:800;margin-top:2px">${liqDD===undefined?'—':tierBadge('−'+Number(liqDD).toFixed(1)+'%',liqDDTier)}</div></div>
        </div>
        ${liqDD!==undefined && Number(liqDD)>=70?'<div class="bad" style="margin-top:8px;padding:10px 12px;border-radius:8px;background:rgba(var(--bad-rgb),.1);font-weight:700;font-size:13px">⚠ NEAR FULL LIQUIDITY DRAIN (≥70% from peak). 9/10 rug scams show this pattern pre-rug.</div>':''}
      </div>
      ${scoreLine}
      ${verdict?`<div style="font-weight:800;font-size:15px;margin:14px 0 0;padding:10px 14px;border-radius:10px;background:var(--card-bg);border:1px solid var(--line)">Verdict: <span class="${verdictCls}" style="font-size:16px;letter-spacing:.2px">${htmlEscape(verdict)}</span></div>`:''}
      ${(payload.invariants?.gaps||[]).filter(g=>/dead_volume|rug_/.test(g)).length?`<div class="warn" style="margin-top:12px;font-size:12px">⚠ Rule / data gaps: ${payload.invariants.gaps.filter(g=>/dead_volume|rug_/.test(g)).map(g=>htmlEscape(g)).join(' · ')}</div>`:''}
    </div>
    <div id="rc-section-mkt" class="rc-tab">
      <div style="font-weight:800;font-size:14px;margin-bottom:8px">📊 Markets · Buy/Sell Money Flow by Time Window</div>
      <table class="rc-tbl">
        <thead><tr><th>WIN</th><th>VOL$</th><th>BUY$</th><th>SELL$</th><th>B%</th><th>BUYS</th><th>SELLS</th><th>TRADE B%</th><th>WALLETS</th><th>NET FLOW$</th></tr></thead>
        <tbody>${marketTableRows || '<tr><td colspan=10 style="padding:14px;text-align:center" class="subtle">No money flow data returned from Birdeye API yet (try token with >0 trade volume).</td></tr>'}</tbody>
      </table>
    </div>
    <div id="rc-section-ins" class="rc-tab">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
        <span style="font-weight:800;font-size:14px">🧠 Insiders · Cohort Breakdown</span>
        <div style="flex:1"></div>
        <span class="subtle" style="font-size:11px;font-weight:600">Advanced Security (21 CU) · One call</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px">${cohortHtml}</div>
      <div class="subtle" style="font-size:11.5px;margin-top:10px">Source: Birdeye advanced security v2 / token holder-profile endpoint — cohort percent of supply owned by each investor archetype. ≥15% any single non-SM cohort = elevated risk. Wallet counts estimated from total_holders × % when absolute count not in API payload.</div>
    </div>
    <div id="rc-section-hld" class="rc-tab">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="font-weight:800;font-size:14px">👥 Holders · Top Ownership</span>
        <div style="flex:1"></div>
        ${tierBadge('Top 10 = '+s.top10.toFixed(2)+'%', s.top10>=60?'danger':(s.top10>=40?'warn':'safe'))}
        ${tierBadge('Creator/Dev = '+s.devPct.toFixed(2)+'%', s.devPct>=15?'high':(s.devPct>=5?'warn':'safe'))}
        ${tierBadge('Holder Distribution (30 CU) · Top N = '+String(holders.length||0), 'low')}
      </div>
      <table class="rc-tbl">
        <thead><tr><th style="width:44px">#</th><th style="min-width:160px">LABEL / TAG</th><th>OWNER</th><th style="width:110px">% SUPPLY</th><th style="width:120px">VALUE USD</th><th>AMOUNT TOKENS</th></tr></thead>
        <tbody>${holdersRowsHtml || '<tr><td colspan=6 style="padding:14px;text-align:center" class="subtle">No holder list rows returned → use --rug-show-holders YES + retry. If still empty check Birdeye x-chain header or contract exists.</td></tr>'}</tbody>
      </table>
    </div>
    <div id="rc-section-lp" class="rc-tab">
      <div style="font-weight:800;font-size:14px;margin-bottom:8px">🔒 Lockers & LP · Auth / Mint / Drain checks</div>
      <div style="border:1px solid var(--line);border-radius:12px;background:var(--card-bg);padding:4px 0">${lockersHtml}</div>
    </div>
    <script nonce="abc123">
      (function(){
        var root = document.getElementById('rug_root');
        if(!root) return;
        var buttons = root.querySelectorAll('.tabber button[data-rc-tab]');
        var sections = ['ovr','mkt','ins','hld','lp'].map(function(k){ return document.getElementById('rc-section-'+k); }).filter(Boolean);
        function setActive(target){
          buttons.forEach(function(b){ b.classList.toggle('on', (b.dataset.rcTab||b.dataset.rc_tab)===target); });
          sections.forEach(function(sec){
            var secKey = sec.id.replace('rc-section-','');
            sec.classList.toggle('on', secKey===target);
          });
        }
        buttons.forEach(function(b){
          b.addEventListener('click', function(ev){
            ev.preventDefault();
            var target = b.dataset.rcTab || b.dataset.rc_tab;
            setActive(target);
            var tgt = document.getElementById('rc-section-'+target);
            if(tgt && typeof tgt.scrollIntoView==='function'){
              try { tgt.scrollIntoView({behavior:'smooth', block:'start'}); } catch(e){}
            }
          });
        });
        var firstTgt = (buttons[0] && (buttons[0].dataset.rcTab||buttons[0].dataset.rc_tab)) || 'ovr';
        setActive(firstTgt);
      })();
    </`+`script>
  </div>`;
}
function parseScoreLine(line){ const out={}; for(const k of ['SEC','SMKT','ACT','VOL','FINAL']){ const m = new RegExp(k+'\\s+([\\d.]+)\\s*/\\s*10').exec(line); if(m) out[k.toLowerCase()]=parseFloat(m[1]);} return out;}
function makeDDRender(stdout){
  const lines = (stdout||'').split(/\r?\n/);
  const st = {header:[], risk:[], priceLine:'', bsh:null, sm:null, score:null, verdict:null, footers:[]};
  let cur=null;
  for(const line of lines){
    const t=line.trim();
    if(t.startsWith('---')) continue;
    if(t.startsWith('🛡') || ((/^\s*(SOL|BSC|BASE|ETH)\b/i.test(line)) && line.includes('$') && !st.header.length)){ st.header.push(line); continue; }
    const tu = t.toUpperCase();
    if(tu.startsWith('RISK / SECURITY')){ cur='risk'; continue; }
    if(tu.startsWith('PRICE')){ cur='price'; continue; }
    if(tu.startsWith('BUY/SELL')){ cur='bs'; st.bsh={head:null,rows:[]}; continue; }
    if(tu.startsWith('SMART MONEY')){ cur='sm'; continue; }
    if(t.startsWith('SCORES') || t.includes('⭐ FINAL')){ st.score=parseScoreLine(line); }
    if(t.startsWith('VERDICT:')){ st.verdict=t.replace(/^VERDICT:\s*/,''); }
    if(t.startsWith('⚡CU:') || t.startsWith('⚠ ') || t.startsWith('✅ ')){ st.footers.push(t); continue; }
    if(cur==='risk' && t) st.risk.push(t);
    if(cur==='price' && /5m/.test(t) && /24h/.test(t)) st.priceLine = t;
    if(cur==='bs' && t){ if(/^win\s/i.test(t)) st.bsh.head=t; else if(/^\s*(5m|15m|30m|1h|2h|4h|8h|24h)\s/.test(t)) st.bsh.rows.push(t); }
    if(cur==='sm' && t) st.sm = (st.sm? st.sm+'\n  ':'')+t;
  }
  const cell=(k,n,final=false)=>_scoreCellHTML(k,n,final);
  const riskRow = ln=>{
    let cls='subtle'; if(/🔴/.test(ln)) cls='bad'; else if(/⚠/.test(ln)) cls='warn'; else if(/✅/.test(ln)) cls='good';
    return `<div class="pillr"><span class="${cls}">${htmlEscape(ln)}</span></div>`;
  };
  const vclass=(v)=>(/STRONG BUY|BUY/.test(v||'')?'good':/AVOID|SELL/.test(v||'')?'bad':'warn');
  const bs = (b)=>{
    if(!b||!b.rows.length) return '';
    const col='Vol$ Buy$ Sell$ B% Buys Sells TradeB% Wallets NetFlow$'.split(' ');
    return `<div><div class="section-title">Buy/Sell + Money Flow</div>
      <table class="t" style="margin-top:6px"><thead><tr><th class="sym">win</th>${col.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>
        ${b.rows.map(row=>{
          const bits=row.trim().split(/\s+/); const [win,...rest]=bits;
          const pad=n=>`<td>${htmlEscape(rest[n-1]||'')}</td>`;
          return `<tr><td class="sym">${htmlEscape(win||'')}</td>${pad(1)}${pad(2)}${pad(3)}${pad(4)}${pad(5)}${pad(6)}${pad(7)}${pad(8)}${pad(9)}</tr>`;
        }).join('')}
      </tbody></table></div>`;
  };
  const hb = st.header.map(l=>`<div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px">${htmlEscape(l)}</div>`).join('');
  return `<div class="render">${hb}
    <div><div class="section-title">Risk / Security</div>
      <div class="copyrow" style="margin-top:6px">${st.risk.map(riskRow).join('')||'<span class="subtle">—</span>'}</div></div>
    <div><div class="section-title">Price Δ%</div>
      <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;margin-top:6px">${htmlEscape(st.priceLine||'—')}</div></div>
    ${bs(st.bsh)}
    <div><div class="section-title">Smart Money</div>
      <div style="margin-top:6px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px">${htmlEscape(st.sm||'—')}</div></div>
    <div class="scorebar">${st.score? (cell('SEC',st.score.sec)+cell('SMKT',st.score.smkt)+cell('ACT',st.score.act)+cell('VOL',st.score.vol)+cell('FINAL',st.score.final,true)) : '<span class="subtle">scores unavailable</span>'}</div>
    ${st.verdict? `<div>Verdict: <span class="verd ${vclass(st.verdict)}">${htmlEscape(st.verdict)}</span></div>`:''}
    <div class="meta">${st.footers.map(f=>`<span class="chip">${htmlEscape(f)}</span>`).join('')}</div>
  </div>`;
}

function _fmtUSD(v, nd=1){
  if(v==null||v===''||isNaN(Number(v))) return 'N/A';
  v=Number(v);
  if(v===0) return '$0';
  const sign = v<0?'-':''; const av=Math.abs(v);
  if(av>=1e9) return sign+'$'+(av/1e9).toFixed(nd)+'B';
  if(av>=1e6) return sign+'$'+(av/1e6).toFixed(nd)+'M';
  if(av>=1e3) return sign+'$'+(av/1e3).toFixed(nd)+'K';
  if(av>=1) return sign+'$'+av.toFixed(nd);
  return sign+'$'+av.toFixed(nd<2?2:nd);
}
function _fmtPctSigned(p){
  if(p==null||p===''||isNaN(Number(p))) return 'N/A';
  const n=Number(p); const s=(n>=0?'+':'')+n.toFixed(1)+'%'; return s;
}
function makeDDRenderFromPayload(payload){
  if(!payload){ return `<div class="render"><div class="bad">Empty DD payload.</div></div>`; }
  const p = payload;
  const cell=(k,n,final=false)=>_scoreCellHTML(k,n,final);
  const riskRow=(txt,cls)=>`<div class="pillr"><span class="${cls||'subtle'}">${htmlEscape(txt)}</span></div>`;
  const vclass=(v)=>(/STRONG BUY|BUY/.test(v||'')?'good':/AVOID|SELL/.test(v||'')?'bad':'warn');
  // ---------- Header ----------
  const chain = (p.params?.chain || 'SOL').toUpperCase();
  const sym = p.symbol || '?';
  const nm  = p.name || sym;
  const prc = Number(p.price_usd);
  const prcStr = isNaN(prc)?'N/A':(prc<1? ('$'+prc.toFixed(6)) : ('$'+prc.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})));
  const mc = _fmtUSD(p.marketcap_usd);
  const liq = _fmtUSD(p.liquidity_usd);
  const fdv = _fmtUSD(p.fdv_usd);
  const hc = p.holder_count==null||isNaN(Number(p.holder_count))? null : Number(p.holder_count).toLocaleString();
  const addr = p.address || '';
  // ---------- Risk / Security ----------
  const sec = p.security || {};
  const risk = [];
  const dev = sec.dev_holding_pct;
  if(dev!=null && !isNaN(Number(dev))){
    const v=Number(dev); const cls = v<2?'good':(v<8?'warn':'bad');
    const mk = v<2?'✅':(v<8?'⚠':'🔴');
    risk.push(riskRow(`Dev hold: ${v.toFixed(1)}% ${mk}`, cls));
  }else risk.push(riskRow('Dev hold: N/A','subtle'));
  const t10 = sec.top10_holder_pct;
  if(t10!=null && !isNaN(Number(t10))){
    const v=Number(t10); const cls = v<20?'good':(v<40?'warn':'bad');
    const mk = v<20?'✅':(v<40?'⚠':'🔴');
    risk.push(riskRow(`Top10: ${v.toFixed(1)}% ${mk}`, cls));
  }else risk.push(riskRow('Top10: N/A','subtle'));
  if(sec.honeypot!=null){
    risk.push(riskRow(`Honeypot: ${sec.honeypot?'🔴 YES':'✅ NO'}`, sec.honeypot?'bad':'good'));
  }
  if(sec.lp_locked!=null){
    risk.push(riskRow(`LP lock: ${sec.lp_locked?'✅ YES':'⚠ NO'}`, sec.lp_locked?'good':'warn'));
  }
  // ---------- Price Δ% ----------
  const pc = (p.price_changes||[]).map(([i,pp])=>{
    const pv = Number(pp); const good = pv>=0;
    const str = i.padStart(4)+' '+_fmtPctSigned(pp).padStart(8);
    return `<span class="${good?'good':'bad'}" style="white-space:pre;font-family:ui-monospace,Menlo,Consolas,monospace">${htmlEscape(str)}</span>`;
  }).join('  ');
  // ---------- Buy/Sell + Money Flow ----------
  const mfMap = {};
  (p.money_flow_rows||[]).forEach(([i,mf])=>{ mfMap[i]=mf; });
  const bsHeaders = ['Vol$','Buy$','Sell$','B%','Buys','Sells','TradeB%','Wallets','NetFlow$'];
  const bsHtml = (p.buy_sell_rows||[]).length ? `<div><div class="section-title">Buy/Sell + Money Flow</div>
    <table class="t" style="margin-top:6px"><thead><tr><th class="sym">win</th>${bsHeaders.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>
    ${(p.buy_sell_rows||[]).map(row=>{
      const [i,t2,b,s2,ratio,buys,sells,tr_ratio,wal] = row;
      const mf = mfMap[i];
      const ratioPct = (ratio==null||isNaN(Number(ratio)))?'N/A':(Number(ratio)*100).toFixed(0)+'%';
      const trPct = (tr_ratio==null||isNaN(Number(tr_ratio)))?'N/A':(Number(tr_ratio)*100).toFixed(0)+'%';
      const buysS = (buys==null||isNaN(Number(buys)))?'N/A':Number(buys).toLocaleString();
      const sellsS = (sells==null||isNaN(Number(sells)))?'N/A':Number(sells).toLocaleString();
      const walS = (wal==null||isNaN(Number(wal)))?'N/A':Number(wal).toLocaleString();
      const nf = _fmtUSD(mf);
      const nfClass = (mf==null||isNaN(Number(mf)))? '': (Number(mf)>=0?'good':'bad');
      return `<tr><td class="sym">${htmlEscape(String(i||''))}</td>
        <td>${_fmtUSD(t2)}</td><td>${_fmtUSD(b)}</td><td>${_fmtUSD(s2)}</td>
        <td>${htmlEscape(ratioPct)}</td><td>${htmlEscape(buysS)}</td><td>${htmlEscape(sellsS)}</td>
        <td>${htmlEscape(trPct)}</td><td>${htmlEscape(walS)}</td>
        <td class="${nfClass}">${nf}</td></tr>`;
    }).join('')}
    </tbody></table></div>` : '';
  // ---------- Smart Money ----------
  const sm = p.smart_money || {};
  let smTxt = '—';
  if(sm.batch_join_success && (sm.smart_traders_no==null||sm.smart_traders_no===''||isNaN(Number(sm.smart_traders_no)))){
    smTxt = 'Not in global smart-money top 100 today (0 SM wallets tracked).';
  }else if(sm.smart_traders_no!=null && !isNaN(Number(sm.smart_traders_no))){
    const n = Number(sm.smart_traders_no);
    const r = sm.rank_in_sm_top100 ? ` (rank #${sm.rank_in_sm_top100}/100)` : '';
    const stars = (n>=30)?'🌟🌟🌟':(n>=10?'🌟🌟':(n>=3?'🌟':''));
    smTxt = `Wallets holding: ${n.toLocaleString()}${r}  ${stars}`;
  }else{
    smTxt = 'Request failed.';
  }
  // ---------- Scores + Verdict ----------
  const sc = p.scores || {};
  const scorebar = (Object.keys(sc).length)?
    (cell('SEC',sc.sec)+cell('SMKT',sc.smkt)+cell('ACT',sc.act)+cell('VOL',sc.vol)+cell('FINAL',sc.final,true))
    : '<span class="subtle">scores unavailable</span>';
  const verdictText = sc.verdict || '';
  // ---------- Footers ----------
  const footers = [];
  footers.push(`⚡CU: ${p.cu_used_total??'N/A'}  (${p.cu_breakdown??''})  |  ⏱${p.latency_ms??'?'}ms  |  📸${p.snapshot_time??''}`);
  const gaps = p.invariants?.gaps || [];
  if(gaps.length){ footers.push(`⚠ ${gaps.length} pipeline gap(s): ${gaps.slice(0,6).join(', ')}${gaps.length>6?' …':''}`); }
  else footers.push('✅ All invariants passed (priceCalc, buySellSum).');
  // ---------- Combine ----------
  const headerHtml =
    `<div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px">🛡  ${htmlEscape(chain+'  '+sym)}   (${htmlEscape(String(nm||'').slice(0,28))})   ${htmlEscape(prcStr)}</div>
     <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:var(--mute)">   MC ${mc} · LIQ ${liq} · FDV ${fdv}${hc?` · Holders ${htmlEscape(hc)}`:''}</div>
     <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--mute);margin-top:2px">   Address: ${htmlEscape(addr||'')}</div>`;
  return `<div class="render">${headerHtml}
    <div style="margin-top:8px"><div class="section-title">Risk / Security</div>
      <div class="copyrow" style="margin-top:6px">${risk.join('')||'<span class="subtle">—</span>'}</div></div>
    <div style="margin-top:8px"><div class="section-title">Price Δ%</div>
      <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;margin-top:6px;overflow-x:auto">${pc||'<span class="subtle">—</span>'}</div></div>
    ${bsHtml}
    <div style="margin-top:8px"><div class="section-title">Smart Money</div>
      <div style="margin-top:6px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px">${htmlEscape(smTxt)}</div></div>
    <div class="scorebar" style="margin-top:10px">${scorebar}</div>
    ${verdictText? `<div style="margin-top:6px">Verdict: <span class="verd ${vclass(verdictText)}">${htmlEscape(verdictText)}</span></div>`:''}
    <div class="meta" style="margin-top:10px">${footers.map(f=>`<span class="chip">${htmlEscape(f)}</span>`).join('')}</div>
  </div>`;
}

// ---------- Suggested Next Actions (after user selects any 1 token from discovery) ----------
function setSelection(o){
  window.STATE.selection = o || null;
  const wrap = $('nextActionsWrap');
  if(!o){ wrap.style.display='none'; return; }
  wrap.style.display='';
  $('selToken').innerHTML = `<b>${htmlEscape(o.sym||'?')}</b> · ${addrCut(o.addr||'',4,6)} · ${htmlEscape(o.chain||'sol')}`;
  // 7 suggested actions (lean UI, no implicit auto-run — user clicks ▶ Run explicitly)
  const acts = [
    {id:'dd', title:'🛡 Token DD (scorecard)', cu:'71 CU', desc:'SEC/SMKT/ACT/VOL/FINAL verdict'},
    {id:'holders', title:'👥 Top 20 Holders', cu:'20 CU', desc:'Holder concentration + dev/top10'},
    {id:'sm_token', title:'🧠 Smart Money in this token', cu:'10 CU', desc:'SM buying/selling activity'},
    {id:'same_plat', title:'🔗 Similar on same platform', cu:'50 CU', desc:'Trending list filtered same platform'},
    {id:'ohlcv', title:'📈 Price OHLCV 7d', cu:'10 CU', desc:'Candles + sparkline chart'},
    {id:'deepsec', title:'🔐 Deep Security Audit', cu:'30 CU', desc:'Honeypot, rug score, LP lock'},
    {id:'open_be', title:'🌐 Open in Birdeye', cu:'0 CU', desc:'Token page on Birdeye.so'},
  ];
  $('nextActions').innerHTML = acts.map(a=>`<div class="card" data-act="${a.id}"><b>${a.title} <span class="tag" style="font-size:10px;color:var(--mute);font-weight:400;margin-left:4px">${a.cu}</span></b><span>${a.desc}</span></div>`).join('');
  $('nextActions').querySelectorAll('[data-act]').forEach(el=>{
    el.onclick=()=>handleNextAction(el.dataset.act, o);
  });
  // Also update dd panel
  if($('dd_address')) $('dd_address').value = o.addr || '';
  if($('dd_chain')) $('dd_chain').value = o.chain || 'sol';
  if($('dd_recent')){
    const prev = $('dd_recent').textContent === '—' ? '' : $('dd_recent').textContent + ' · ';
    $('dd_recent').textContent = prev + (o.sym||'?')+':'+addrCut(o.addr||'',4,4);
  }
  // Prefill TL platform filter if row has platform
  if($('tl_platform') && o.platform) $('tl_platform').value = o.platform;
}
function handleNextAction(act, o){
  // Policy: 100% NO implicit auto-run. Navigate + prefill inputs only.
  // User must click ▶ Run explicitly (saves CU, aligns with lean-UI rules).
  switch(act){
    case 'dd':
      window.STATE.skill='dd';
      if($('dd_address')) $('dd_address').value = o.addr || '';
      if($('dd_chain')) $('dd_chain').value = o.chain || 'sol';
      renderCatalog(); renderSkillCtrl();
      // Show ready banner so user knows prefill happened
      setTimeout(()=>{ const out=$('out'); if(out && !out.querySelector('.card')) out.innerHTML=`<div class="render"><div class="good">✅ Prefilled — ${o.sym||'token'} · ${addrCut(o.addr||'',4,4)} · click ▶ Run to execute (71 CU).</div></div>`; }, 60);
      break;
    case 'holders': case 'stc': case 'sm_token': case 'ohlcv': case 'deepsec':
      window.STATE.skill = {holders:'stc', stc:'stc', sm_token:'sm_flow_token', ohlcv:'chart', deepsec:'security'}[act];
      renderCatalog(); renderSkillCtrl();
      break;
    case 'same_plat':
      window.STATE.skill='tl';
      renderCatalog(); renderSkillCtrl();
      $('tl_platform').value = (o && o.platform) ? o.platform : 'pump.fun';
      setTimeout(()=>{ const out=$('out'); if(out && !out.querySelector('.card')) out.innerHTML=`<div class="render"><div class="good">✅ Prefilled — platform filter = ${$('tl_platform').value} · click ▶ Run to execute.</div></div>`; }, 60);
      break;
    case 'open_be': window.open(`https://birdeye.so/token/${o.addr||''}?chain=${(o.chain||'sol').length<=3? {sol:'solana',eth:'ethereum',bsc:'bsc',base:'base'}[o.chain||'sol'] : (o.chain||'solana')}`, '_blank'); break;
  }
}
function attachSel(root){
  root.querySelectorAll('[data-sel]').forEach(el=>{
    el.onclick = ()=>{
      try{ setSelection(JSON.parse(el.getAttribute('data-sel'))); }catch(e){}
    };
  });
}

// ---------- Run ----------
async function runCLI(side, {formatOverride=null}={}){
  const out = $('out');
  const uiKey = window._SESSION_KEY_MEM || '';

  // ===== PREFLIGHT (0 CU) — FAIL fast, NO /api/run POST =====
  const keyOk = await _keySetOk();
  if(!keyOk){
    out.innerHTML = `<div class="render"><div class="bad">🛑 API key NOT SET. Paste key in 🔑 API Key panel (sidebar) → Apply session, then retry.</div></div>`;
    return;
  }
  let script='birdeye_cli', argv=[], payloadKey='';
  let fmtChosen = '', fmtUse = '';
  let kindHint = side==='dd' ? 'token-dd' : (side==='rca' ? 'rugcheck-audit' : (side==='sm' ? 'smart-money-profile-v1' : (side==='wa' ? 'wallet-analysis-v1' : 'trending-list')));
  if(side==='tl'){
    fmtChosen = formatOverride || 'render';
    fmtUse = (fmtChosen==='render') ? 'raw-json' : fmtChosen;
    const chain = $('tl_chain')?.value || 'sol';
    const isV3 = (window.STATE.skill==='tl_v3');
    const interval = '24h';
    const source = isV3 ? 'v3-list' : 'v3-list';
    const sortBy = 'volumeUSD';
    const limit = '50';
    argv = ['trending-list','--chain',chain,'--interval',interval,
      '--source',source,'--sort-by',sortBy,'--limit',limit,
      '--format',fmtUse];
    payloadKey = (fmtChosen==='render' ? 'render-tl' : fmtUse);
    kindHint = 'trending-list';
  }else if(side==='dd'){
    const addr = ($('dd_address')?.value || window.STATE.selection?.addr || '').trim();
    const chain = $('dd_chain')?.value || 'sol';
    fmtChosen = formatOverride || 'render';
    fmtUse = (fmtChosen==='render') ? 'scorecard' : fmtChosen;
    const a = validateAnyAddr(addr, chain);
    if(!a.ok){ out.innerHTML = `<div class="render"><div class="bad">🛑 ${a.msg}</div></div>`; return; }
    argv = ['token-dd','--chain',chain,'--address',addr,'--format',fmtUse];
    payloadKey = (fmtChosen==='render' ? 'render-dd' : fmtUse);
    kindHint = 'token-dd';
  }else if(side==='sm'){
    // Skill #9 Smart Money Profile — single-wallet behavior analysis
    fmtChosen = formatOverride || selectedFmt('sm');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    const chainSm = ($('dd_chain')?.value || 'sol');
    const walletSm = ($('sm9_wallet')?.value || '').trim();
    if(!walletSm){ out.innerHTML = `<div class="render"><div class="bad">🛑 Wallet address is required.</div></div>`; return; }
    argv = ['--nocache', 'smart-money-profile',
      '--chain', chainSm,
      '--wallet', walletSm,
      '--pnl-method', ($('sm9_pnl')?.value || 'wac'),
      '--format', fmtUse];
    if($('sm9_skip_tx')?.checked) argv.push('--skip-tx-list');
    if($('sm9_skip_first')?.checked) argv.push('--skip-first-tx');
    payloadKey = (fmtChosen==='render' ? 'render-sm' : fmtUse);
    kindHint = 'smart-money-profile-v1';
  }else if(side==='wa'){
    // Skill #14 Wallet Analysis — single-wallet deep-dive by intervals
    fmtChosen = formatOverride || selectedFmt('wa');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    const chainWa = ($('wa_chain')?.value || 'sol');
    const walletWa = ($('wa_wallet')?.value || '').trim();
    if(!walletWa){ out.innerHTML = `<div class="render"><div class="bad">🛑 Wallet address is required.</div></div>`; return; }
    argv = ['--nocache', 'wallet-analysis',
      '--chain', chainWa,
      '--wallet', walletWa,
      '--horizon', ($('wa_horizon')?.value || 'normal'),
      '--pnl-method', ($('wa_pnl')?.value || 'wac'),
      '--format', fmtUse];
    if($('wa_skip_tx')?.checked) argv.push('--skip-tx-list');
    if($('wa_skip_first')?.checked) argv.push('--skip-first-tx');
    if($('wa_skip_port')?.checked) argv.push('--skip-portfolio');
    payloadKey = (fmtChosen==='render' ? 'render-wa' : fmtUse);
    kindHint = 'wallet-analysis-v1';
  }else if(side==='rca'){
    // Skill #17b RugCheck Audit standalone — flow sẵn: 24h liq, top20 holders YES, render UI
    fmtChosen = formatOverride || 'render';
    fmtUse = (fmtChosen==='render') ? 'raw-json' : fmtChosen;
    const addrR = ($('rca_address')?.value || window.STATE.selection?.addr || '').trim();
    const chainR = $('rca_chain')?.value || 'sol';
    const liqWin = '24h';
    const showHolders = true;
    const hN = 20;
    const va = validateAnyAddr(addrR, chainR);
    if(!va.ok){ out.innerHTML = `<div class="render"><div class="bad">🛑 ${va.msg}</div></div>`; return; }
    argv = ['rugcheck-audit','--chain',chainR,'--address',addrR,
      '--rug-liq-window', liqWin,
      '--rug-holders-top-n', String(hN),
      '--format', fmtUse];
    if(!showHolders) argv.push('--no-rug-show-holders');
    payloadKey = (fmtChosen==='render' ? 'render-rca' : fmtUse);
    kindHint = 'rugcheck-audit';
  }else if(side==='stc'){
    // Skill #6 · Spam Token Cleaner (stc) — script="stc" not birdeye_cli.
    script = 'stc';
    fmtChosen = formatOverride || selectedFmt('stc');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    const minMc = Number($('stc_min_mc')?.value || 1e9);
    const maxVol = Number($('stc_max_vol')?.value || 50);
    const chains = ($('stc_chains')?.value || 'solana').trim();
    const maxTokens = Math.max(1, Number($('stc_max_tokens')?.value || 5));
    argv = [
      '--min-mc', String(Math.round(minMc)),
      '--max-vol', String(maxVol),
      '--chains', chains,
      '--max-tokens', String(Math.round(maxTokens)),
      '--format', fmtUse
    ];
    payloadKey = (fmtChosen==='render') ? 'render-stc' : fmtUse;
    kindHint = 'stc';
  }else if(side==='wallet_score'){
    // Skill #13 Wallet Score — birdeye_cli wallet-score subcommand
    // --nocache ensures clicking ▶ Run ALWAYS fetches fresh API data
    // (history tab re-renders use --from-cache instead, at 0 CU).
    script = 'birdeye_cli';
    const addrW = ($('ws_address')?.value || window.STATE.selection?.wallet || window.STATE.selection?.addr || '').trim();
    const chainW = $('ws_chain')?.value || 'sol';
    const durationW = $('ws_duration')?.value || '30d';
    const methodW = $('ws_pnl_method')?.value || 'wac';
    const skipRug = !!$('ws_skip_rug')?.checked;
    const skipFTx  = !!$('ws_skip_first_tx')?.checked;
    const skipPf   = !!$('ws_skip_portfolio')?.checked;
    const incStyle = !!$('ws_include_style')?.checked;
    if(!addrW){ out.innerHTML = `<div class="render"><div class="bad">🛑 Wallet address is required. Paste it in the Skill #13 Wallet Score panel.</div></div>`; return; }
    fmtChosen = formatOverride || selectedFmt('wallet_score');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['--nocache', 'wallet-score', '--chain', chainW, '--wallet', addrW,
      '--duration', durationW, '--pnl-method', methodW, '--format', fmtUse];
    if(skipRug) argv.push('--skip-rug');
    if(skipFTx) argv.push('--skip-first-tx');
    if(skipPf)  argv.push('--skip-portfolio');
    if(incStyle) argv.push('--include-style');
    payloadKey = (fmtChosen==='render') ? 'render-wallet-score' : fmtUse;
    kindHint = 'wallet-score';
  }else if(side==='wallet_style'){
    // Skill #11 Wallet Style — birdeye_cli wallet-style subcommand
    script = 'birdeye_cli';
    const addrWS = ($('wst_address')?.value || window.STATE.selection?.wallet || window.STATE.selection?.addr || '').trim();
    const chainWS = $('wst_chain')?.value || 'sol';
    const durationWS = $('wst_duration')?.value || '30d';
    const methodWS = $('wst_pnl_method')?.value || 'wac';
    const skipTxListWS = !!$('wst_skip_tx_list')?.checked;
    const skipFTxWS  = !!$('wst_skip_first_tx')?.checked;
    if(!addrWS){ out.innerHTML = `<div class="render"><div class="bad">🛑 Wallet address is required. Paste it in the Skill #11 Wallet Style panel.</div></div>`; return; }
    fmtChosen = formatOverride || selectedFmt('wallet_style');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['--nocache', 'wallet-style', '--chain', chainWS, '--wallet', addrWS,
      '--duration', durationWS, '--pnl-method', methodWS, '--format', fmtUse];
    if(skipTxListWS) argv.push('--skip-tx-list');
    if(skipFTxWS)  argv.push('--skip-first-tx');
    payloadKey = (fmtChosen==='render') ? 'render-wallet-style' : fmtUse;
    kindHint = 'wallet-style-v1';
  }else if(side==='kline_pattern'){
    // Skill #21 Kline Pattern — birdeye_cli kline-pattern subcommand
    script = 'birdeye_cli';
    const addrKP = ($('kp_address')?.value || window.STATE.selection?.address || window.STATE.selection?.addr || window.STATE.selection?.token || '').trim();
    const chainKP = $('kp_chain')?.value || 'sol';
    const resKP = $('kp_resolution')?.value || '15m';
    const winKP = $('kp_window')?.value || '7d';
    if(!addrKP){ out.innerHTML = `<div class="render"><div class="bad">🛑 Token address is required. Paste it in the Skill #21 Kline Pattern panel.</div></div>`; return; }
    fmtChosen = formatOverride || selectedFmt('kline_pattern');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['--nocache', 'kline-pattern', '--chain', chainKP, '--address', addrKP,
      '--resolution', resKP, '--window', winKP, '--format', fmtUse];
    payloadKey = (fmtChosen==='render') ? 'render-kline-pattern' : fmtUse;
    kindHint = 'kline-pattern-v1';
  }else if(side==='trending_score'){
    // Skill #22 Token Trending Score — birdeye_cli token-trending-score subcommand
    script = 'birdeye_cli';
    const addrTS = ($('ts_address')?.value || window.STATE.selection?.address || window.STATE.selection?.addr || window.STATE.selection?.token || '').trim();
    const chainTS = $('ts_chain')?.value || 'sol';
    const candlesTS = $('ts_candles')?.value || '5000';
    if(!addrTS){ out.innerHTML = `<div class="render"><div class="bad">🛑 Token address is required. Paste it in the Skill #22 Token Trending Score panel.</div></div>`; return; }
    fmtChosen = formatOverride || selectedFmt('trending_score');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['token-trending-score', '--chain', chainTS, '--address', addrTS,
      '--candles', candlesTS, '--format', fmtUse];
    payloadKey = (fmtChosen==='render') ? 'render-trending-score' : fmtUse;
    kindHint = 'token-trending-score-v1';
  }else if(side==='contract_dd'){
    // Skill #5 Contract DD — birdeye_cli contract-dd subcommand
    script = 'birdeye_cli';
    const addrCDD = ($('cdd_address')?.value || window.STATE.selection?.address || window.STATE.selection?.addr || window.STATE.selection?.token || '').trim();
    const chainCDD = $('cdd_chain')?.value || 'sol';
    const skipKlineCDD = !!$('cdd_skip_kline')?.checked;
    if(!addrCDD){ out.innerHTML = `<div class="render"><div class="bad">🛑 Token address is required. Paste it in the Skill #5 Contract DD panel.</div></div>`; return; }
    fmtChosen = formatOverride || selectedFmt('contract_dd');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['--nocache', 'contract-dd', '--chain', chainCDD, '--address', addrCDD, '--format', fmtUse];
    if(skipKlineCDD) argv.push('--skip-kline');
    payloadKey = (fmtChosen==='render' ? 'render-contract-dd' : fmtUse);
    kindHint = 'contract-dd-v1';
  }else if(side==='junk_predict'){
    script = 'birdeye_cli';
    const chainJ = $('junk_chain')?.value || 'sol';
    const tokensRaw = ($('junk_tokens')?.value || '').trim();
    const tokens = tokensRaw ? tokensRaw.split(/[\s,]+/).filter(Boolean).join(',') : '';
    if(!tokens){ out.innerHTML = `<div class="render"><div class="bad">🛑 Paste at least one token address.</div></div>`; return; }
    fmtChosen = formatOverride || selectedFmt('junk');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['junk-predict', '--chain', chainJ, '--tokens', tokens, '--format', fmtUse];
    payloadKey = (fmtChosen==='render' ? 'render-junk' : fmtUse);
    kindHint = 'junk-predict-v1';
  }else if(side==='junk_quick_test'){
    script = 'birdeye_cli';
    const chainQ = $('junk_chain')?.value || 'sol';
    fmtChosen = formatOverride || selectedFmt('junk');
    fmtUse = (fmtChosen==='render') ? 'rendered' : fmtChosen;
    argv = ['junk-quick-test', '--chain', chainQ, '--num', '30', '--format', fmtUse];
    payloadKey = (fmtChosen==='render' ? 'render-junk' : fmtUse);
    kindHint = 'junk-quick-test-v1';
  }else{
    out.innerHTML = `<div class="render"><div class="warn">Skill ${side} WIP.</div></div>`; return;
  }
  out.innerHTML = `<div class="render"><div><span class="loading">⟳</span> Running ${side.toUpperCase()}…</div></div>`;
  try{
    const j = await runScript(script, argv, {uiKey});
    const cmd = cmdText(script, argv);
    // Parse #RUN_ID first line from stdout
    let stdoutClean = j.stdout || '';
    let runId = null, cuTotal = null;
    const firstLineRe = /^#RUN_ID\s+(\S+)\t(\S*)\tcu=(\d+)\r?\n?/;
    const m = firstLineRe.exec(stdoutClean);
    if(m){
      runId = m[1];
      cuTotal = parseInt(m[3], 10) || null;
      stdoutClean = stdoutClean.substring(m[0].length);
    }
    // If CLI raw-json mode had runId inside envelope, try that too as fallback
    if(!runId && payloadKey && (payloadKey==='render-tl' || payloadKey==='render-sm' || fmtUse==='raw-json')){
      try{
        const env = typeof j.stdout === 'string' ? JSON.parse(j.stdout) : j.stdout;
        if(env && env.runId){ runId = env.runId; cuTotal = cuTotal ?? env.cu_used_total ?? null; }
      }catch(_){}
    }
    // Store STATE.lastRun for 0-CU format switch
    const fmtChosenNow = formatOverride || selectedFmt(side);
    window.__lastFmtCu = cuTotal || window.__lastFmtCu || 0;
    if(runId){
      window.STATE.lastRun = { runId, side, kind: kindHint, cu_used_total: cuTotal, lastFmt: fmtChosenNow, script, argv: [...argv] };
    }
    let bodyBlock;
    if(payloadKey==='render-tl'){
      let p = stdoutClean; try{p = JSON.parse(stdoutClean);}catch(e){}
      // Raw-json envelope may be {runId, payload: {...}}
      const actualPayload = (p && p.payload && p.payload.rows) ? p.payload : p;
      const src = Array.isArray(argv)? (argv.includes('v3-list')?'v3-list':'trending') : 'trending';
      bodyBlock = makeTrendRender(actualPayload, src) +
        `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
    }else if(payloadKey==='render-dd'){
      bodyBlock = makeDDRender(stdoutClean);
    }else if(payloadKey==='render-sm'){
      // Skill #9 · Smart Money Profile rendered output. JSON envelope {html, profile, ...}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
      }
    }else if(payloadKey==='render-wa'){
      // Skill #14 · Wallet Analysis rendered output. JSON envelope {html, profile, assets, ...}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
      }
    }else if(payloadKey==='render-rca'){
      // Skill #17b RugCheck Audit UI = same same rugcheck.xyz layout = 5 tabs.
      let p = stdoutClean; try{p = JSON.parse(stdoutClean);}catch(e){}
      const payload = (p && p.payload) ? p.payload : (p && p.overview ? p : null);
      if(payload){
        bodyBlock = makeRugCheckRender(payload, j) +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        bodyBlock = `<div class="render"><div class="warn">⚠ Unable to parse RugCheck payload → fallback render as DD scorecard (showing raw stdout)</div></div>${makeDDRender(stdoutClean)}`;
      }
    }else if(payloadKey==='render-stc'){
      // Skill #6 · Spam Token Cleaner rendered output.
      // stc.py --format rendered may return: (a) JSON envelope with rows + html, (b) raw HTML string <div class=render-stc>, or (c) plain text.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const rows = (parsed && (parsed.rows || (parsed.payload && parsed.payload.rows))) || null;
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else if(Array.isArray(rows) && rows.length){
        const cols = Object.keys(rows[0] || {}).slice(0, 16);
        const header = `<tr>${cols.map(c=>`<th style="position:sticky;top:0;background:var(--card-bg);z-index:1;padding:6px 8px;text-align:left;border-bottom:1px solid var(--line);font-size:11px;white-space:nowrap">${htmlEscape(c.toUpperCase())}</th>`).join('')}</tr>`;
        const rhtml = rows.map((r,i)=>`<tr style="${i%2?'background:rgba(255,255,255,.02)':''}">${cols.map(c=>{const v=r[c]; const s=v==null||v===undefined?'—':(typeof v==='number'?(Number.isInteger(v)?String(v):Number(v).toFixed(c.toLowerCase().includes('pct')?2:4)):String(v)); return `<td style="padding:4px 8px;font-size:11.5px;white-space:nowrap;font-family:${/^[0-9.\-%$,\s]+$/.test(s)?'monospace':'inherit'}">${htmlEscape(s)}</td>`;}).join('')}</tr>`).join('');
        bodyBlock = `<div class="render" style="margin-top:10px"><div class="section-title" style="margin-bottom:6px">🧹 STC Results · ${rows.length} rows · sort = MC desc → TopWalletValue desc → Liq desc → V24h asc</div><div style="overflow-x:auto;max-height:60vh;border:1px solid var(--line);border-radius:10px"><table style="border-collapse:collapse;width:100%">${header}${rhtml}</table></div></div>` +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
      }
    }else if(payloadKey==='render-wallet-score'){
      // Skill #13 · Wallet Score rendered output. JSON envelope {html, metrics, components, step_checks, alpha_score, tier, wallet_info, cu_breakdown}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        // Fallback: extract alpha / tier directly if payload has structured fields
        const data = parsed || {};
        const alpha = data.alpha_score ?? (data.payload && data.payload.alpha_score);
        const tier = data.tier || (data.payload && data.payload.tier);
        if(typeof alpha === 'number'){
          const emoji = tier?.emoji || '🧠';
          const name  = tier?.name  || 'Score';
          bodyBlock = `<div class="render" style="padding:16px 18px;border:1px solid var(--line);border-radius:14px">
            <div style="font-size:28px;font-weight:900">${emoji} ${alpha.toFixed(1)}<span style="font-size:14px;color:var(--mute);margin-left:4px">/100 · ${name}</span></div>
            <div style="margin-top:6px;font-size:12px;color:var(--mute)">⚠ Unable to find rendered HTML (preHtml missing in payload); showing raw envelope below.</div>
          </div><div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
        }else{
          bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
        }
      }
    }else if(payloadKey==='render-wallet-style'){
      // Skill #11 · Wallet Style rendered output. JSON envelope {html, main_title, freq, pnl_level, badges, metrics, ...}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        // Fallback: show style title from payload
        const data = parsed || {};
        const mt = data.main_title || (data.payload && data.payload.main_title) || {};
        if(mt.zh || mt.en){
          bodyBlock = `<div class="render" style="padding:16px 18px;border:1px solid var(--line);border-radius:14px">
            <div style="font-size:26px;font-weight:900">${mt.emoji||'🎭'} ${mt.zh||''}<span style="font-size:13px;color:var(--mute);margin-left:6px">(${mt.en||''})</span></div>
            <div style="margin-top:4px;font-size:12px;color:var(--mute)">Freq ${mt.freq||'?'} · P&amp;L ${mt.pnl||'?'}</div>
            <div style="margin-top:6px;font-size:12px;color:var(--mute)">⚠ Unable to find rendered HTML (preHtml missing in payload); showing raw envelope below.</div>
          </div><div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
        }else{
          bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
        }
      }
    }else if(payloadKey==='render-kline-pattern'){
      // Skill #21 · Kline Pattern rendered output. JSON envelope {html, pattern, score, measurements, label, color}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        const data = parsed || {};
        const pat = data.pattern || (data.payload && data.payload.pattern);
        const score = data.score ?? (data.payload && data.payload.score);
        if(pat || typeof score === 'number'){
          bodyBlock = `<div class="render" style="padding:16px 18px;border:1px solid var(--line);border-radius:14px">
            <div style="font-size:26px;font-weight:900">🕯️ ${pat||'?'} <span style="font-size:14px;color:var(--mute);margin-left:6px">${score??'?'}/100</span></div>
            <div style="margin-top:6px;font-size:12px;color:var(--mute)">⚠ Unable to find rendered HTML (preHtml missing in payload); showing raw envelope below.</div>
          </div><div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
        }else{
          bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
        }
      }
    }else if(payloadKey==='render-trending-score'){
      // Skill #22 · Token Trending Score rendered output. JSON envelope {html, overall_trending_score, intervals, ...}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        const data = parsed || {};
        const ov = data.overall_trending_score ?? (data.payload && data.payload.overall_trending_score);
        if(typeof ov === 'number'){
          bodyBlock = `<div class="render" style="padding:16px 18px;border:1px solid var(--line);border-radius:14px">
            <div style="font-size:28px;font-weight:900">📈 ${ov.toFixed(1)}<span style="font-size:14px;color:var(--mute);margin-left:4px">/100 · Token Trending Score</span></div>
            <div style="margin-top:6px;font-size:12px;color:var(--mute)">⚠ Unable to find rendered HTML (preHtml missing in payload); showing raw envelope below.</div>
          </div><div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
        }else{
          bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
        }
      }
    }else if(payloadKey==='render-contract-dd'){
      // Skill #5 · Contract DD rendered output. JSON envelope {html, composite, tier, safety_score, ...}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        const data = parsed || {};
        const comp = data.composite ?? (data.payload && data.payload.composite);
        const tier = data.tier || (data.payload && data.payload.tier);
        if(typeof comp === 'number'){
          bodyBlock = `<div class="render" style="padding:16px 18px;border:1px solid var(--line);border-radius:14px">
            <div style="font-size:28px;font-weight:900">🛡️ ${comp.toFixed(1)}<span style="font-size:14px;color:var(--mute);margin-left:4px">/100 · ${tier?.name||'Contract DD'}</span></div>
            <div style="margin-top:6px;font-size:12px;color:var(--mute)">⚠ Unable to find rendered HTML (preHtml missing in payload); showing raw envelope below.</div>
          </div><div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
        }else{
          bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
        }
      }
    }else if(payloadKey==='render-junk'){
      // Skill #32 · Junk Token Prediction rendered output. JSON envelope {html, results, threshold, n_junk, ...}.
      let parsed = null;
      try{ if(stdoutClean && typeof stdoutClean === 'string' && /^\s*\{/.test(stdoutClean)) parsed = JSON.parse(stdoutClean); }catch(_){}
      const preHtml = (parsed && (parsed.html || (parsed.payload && parsed.payload.html))) || null;
      if(preHtml && typeof preHtml === 'string' && preHtml.trim().length){
        bodyBlock = preHtml +
          `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }else{
        const data = parsed || {};
        const nJunk = data.n_junk ?? (data.payload && data.payload.n_junk);
        const nTok = data.n_tokens ?? (data.payload && data.payload.n_tokens);
        bodyBlock = `<div class="render" style="padding:16px 18px;border:1px solid var(--line);border-radius:14px">
          <div style="font-size:22px;font-weight:900">🗑️ Junk Prediction · ${nJunk??0}/${nTok??0} JUNK</div>
          <div style="margin-top:6px;font-size:12px;color:var(--mute)">⚠ Showing raw envelope below (rendered HTML missing).</div>
        </div><div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout</div><pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre></div>`;
      }
    }else{
      bodyBlock = `<pre class="out_body">${htmlEscape(stdoutClean||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
    }
    const fmtBarHtmlOut = runId ? fmtButtonsHtml(fmtChosenNow, runId, kindHint) : '';
    const cuChipText = cuTotal != null ? `⚡CU: ${cuTotal}` : '⚡CU · see inside footer';
    out.innerHTML = `${fmtBarHtmlOut}
      <div class="cmd" style="display:flex;align-items:center;gap:8px"><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${htmlEscape(cmd)}</span><button class="btn ghost" type="button" style="padding:2px 8px;font-size:12px;flex-shrink:0" title="Copy full CLI command" onclick="const t=this.previousElementSibling.textContent;navigator.clipboard.writeText(t).then(()=>{this.textContent='✓';setTimeout(()=>this.textContent='📋',1000)})">📋</button></div>
      <div class="meta">
        <span class="chip">exit: ${j.exit}</span>
        ${j.stderr? `<span class="chip bad">stderr</span>`:''}
        <span class="chip">${j.duration_ms ?? '?'} ms</span>
        <span class="chip cu">${cuChipText}</span>
        ${runId?`<span class="chip good">💾 cached · runId=${htmlEscape(runId.slice(0,22))}…</span>`:''}
      </div>
      ${bodyBlock}`;
    attachSel(out);
    refreshHistory();
  }catch(e){
    out.innerHTML = `<div class="render"><div class="bad">Error: ${htmlEscape(e.message||String(e))}</div></div>`;
  }
}

document.querySelectorAll('[data-quick]').forEach(b=>{
  b.onclick=()=>{
    const q=b.dataset.quick;
    const catId = (q==='hee'||q==='spcx') ? 'token-dd' : 'discovery';
    if(window.STATE.mode!=='drill'){ drillMode(catId); }
    if(q==='hot'){ window.STATE.skill='tl'; renderCatalog(); renderSkillCtrl(); }
    else if(q==='pump'){
      window.STATE.skill='tl'; renderCatalog(); renderSkillCtrl();
      const e=$('tl_platform'); if(e) e.value='pump.fun';
    }
    else if(q==='hee' || q==='spcx'){
      const addr = q==='hee' ? 'DaZG1BGU7ZRfoSAy3vWAtMmcMc2sdxcyZuAamxmLjH4' : 'SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb';
      window.STATE.skill='dd'; renderCatalog(); renderSkillCtrl();
      setSelection({addr, sym:q==='hee'?'HeeHaw':'SPCX', chain:'sol'});
    }
  };
});

// ---------- Theme toggle ----------
function applyTheme(t){
  if(!t) t = 'dark';
  if(t !== 'dark' && t !== 'light') t = 'dark';
  try { localStorage.setItem('be.theme', t); } catch(e){}
  document.documentElement.setAttribute('data-theme', t);
  var btn = $('themeToggleBtn');
  if(btn){
    btn.textContent = (t === 'dark') ? '☀️' : '🌙';
    btn.title = (t === 'dark') ? 'Switch to light mode' : 'Switch to dark mode';
  }
}
function toggleTheme(){
  var cur = 'dark';
  try { cur = localStorage.getItem('be.theme') || 'dark'; } catch(e){}
  applyTheme( cur === 'dark' ? 'light' : 'dark' );
}
try {
  // mirror early <head> inline script to align button icon on first paint
  var _t = localStorage.getItem('be.theme') || 'dark';
  applyTheme(_t);
} catch(e){}

// ---------- Boot ----------
(async function boot(){
  await loadCatalog();
  applyTheme( (function(){ try { return localStorage.getItem('be.theme') || 'dark'; } catch(e){ return 'dark'; } })() );
  // Wire banner buttons (exist regardless of view)
  $('themeToggleBtn').onclick = ()=>toggleTheme();
  $('hotReloadBtn').onclick = ()=>location.reload();
  $('docsBtn').onclick = ()=>window.open('https://data.birdeye.so/docs/llms.txt', '_blank');
  $('goHubBtn').onclick = ()=>goHome();
  $('ver').onclick = ()=>location.reload();
  // Sidebar key eye toggle
  $('pasteKey_eye') && ($('pasteKey_eye').onclick = ()=>_toggleKeyEye('pasteKey'));
  // If key was previously applied in this session (masked marker in LS), sync UI state dots
  try{
    if((localStorage.getItem(LSKEY_SESSION_PASTE)||'') === '__MASKED_APPLIED__'){
      if($('pasteKey')){ $('pasteKey').value='••••••••••••••••'; $('pasteKey').type='password'; $('pasteKey').dataset.masked='1'; }
    }
  }catch(e){}
  // ===== Floating chat widget (feature flag off — lean UI) =====
  // Widget is commented out in HTML. Uncomment block + block below to enable.
  // (function(){
  //   const tog = $('chatToggleBtn');
  //   const close = $('chatCloseBtn');
  //   const send = $('chatSendBtn');
  //   const inp = $('chatInput');
  //   if(tog) tog.onclick = ()=>{ const b=$('chatBox'); if(!b) return; const v=b.style.display!=='flex'; b.style.display= v?'flex':'none'; if(v) setTimeout(()=>inp&&inp.focus(),120); };
  //   if(close) close.onclick = ()=>{ const b=$('chatBox'); if(b) b.style.display='none'; };
  //   if(send) send.onclick = ()=>_handleChatSend();
  //   if(inp) inp.addEventListener('keydown', (e)=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); _handleChatSend(); }});
  //   try{ fetch('/api/ai-key-info').then(r=>r.json()).then(j=>{
  //     Object.entries(j.providers||{}).forEach(([p,s])=>{
  //       if(s.key_set && !window._SESSION_AI_KEYS[p]){ window._SESSION_AI_KEYS[p]='__ENV_LOADED__'; }
  //     });
  //   }).catch(()=>{}); }catch(_){}
  // })();
  const qs = new URLSearchParams(window.location.search);
  if(APP_PAGE === 'detail'){
    let skill = qs.get('skill') || null;
    let group = null;
    if(skill){
      group = CATALOG.find(g => (g.items || []).some(it => it.id === skill)) || null;
    }
    const catQ = qs.get('cat') || '';
    if(!group && catQ){
      group = CATALOG.find(g => catIdOf(g) === catQ) || null;
    }
    if(!group) group = CATALOG[0] || null;
    const catId = group ? catIdOf(group) : 'discovery';
    if(!skill || !(group && (group.items || []).some(it => it.id === skill))){
      const live = group && (group.items || []).find(it => it.status === 'live');
      const first = group && (group.items || [])[0];
      skill = (live || first || {}).id || null;
    }
    window.STATE.skill = skill;
    window.STATE.activeCategory = catId;
    window.STATE.homeFilter = catId;
    const idx = CATALOG.findIndex(g => catIdOf(g) === catId);
    drillMode(catId, idx >= 0 ? idx : null);
    window.history.replaceState({}, '', buildDetailUrl(window.STATE.skill, catId));
  }else{
    window.STATE.homeFilter = qs.get('filter') || 'all';
    renderHome();
  }
  await refreshKeyBox();
})();
