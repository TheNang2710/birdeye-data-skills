#!/usr/bin/env python3
"""Minimal Flask-less HTTP UI server for birdeye-screener Layer C CLI.

Two routes:
  GET  /                                   → static HTML UI
  POST /api/run  {script:str, argv:[str]}  → run CLI script (whitelisted) + capture stdout/stderr/exit

Launches:
  python3 scripts/server_ui.py          # default port 8765
  python3 scripts/server_ui.py --port 8888

Designed for LOCAL DEV ONLY (no auth; subprocesses). No deps beyond stdlib.
"""
from __future__ import annotations

import argparse
import cgi
import html
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = HERE  # birdeye-screener/scripts/
CLI_PATH = SCRIPTS / "birdeye_cli.py"
SCREENER_PATH = SCRIPTS / "birdeye_screener.py"
SIMPLE_PATH = SCRIPTS / "birdeye_trending_simple.py"

ALLOWED_SCRIPTS = {
    "birdeye_cli": str(CLI_PATH),
    "birdeye_screener": str(SCREENER_PATH),
    "birdeye_trending_simple": str(SIMPLE_PATH),
}
PY = sys.executable


UI_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Birdeye Screener — Test UI</title>
<style>
  :root{
    --bg:#0f1115; --panel:#171a21; --line:#262b36; --text:#e6e8ef;
    --mute:#8a93a6; --accent:#6aa6ff; --good:#2ecc71; --warn:#f0b429; --bad:#ef4444;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 ui-sans-serif,-apple-system,"Segoe UI",Inter,system-ui,sans-serif}
  header{padding:12px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px}
  header h1{font-size:15px;margin:0;letter-spacing:.2px}
  header .pill{font-size:12px;color:var(--mute)}
  main{display:grid;grid-template-columns:360px 1fr;min-height:calc(100vh - 49px)}
  @media (max-width: 900px){ main{grid-template-columns:1fr} }
  nav{padding:14px;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:10px}
  .tabs{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:4px}
  .tab{padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);cursor:pointer;text-align:center;font-size:13px}
  .tab.active{border-color:var(--accent);color:var(--accent)}
  .group{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px}
  .row{display:grid;grid-template-columns:96px 1fr;gap:8px;align-items:center}
  .row label{color:var(--mute);font-size:12px}
  input,select,button{font:inherit;color:inherit}
  input[type=text],select{width:100%;background:#10141c;border:1px solid var(--line);border-radius:7px;padding:8px 9px;outline:none}
  input[type=text]:focus,select:focus{border-color:var(--accent)}
  .run{background:linear-gradient(180deg,#3473e6,#2860c8);border:none;border-radius:8px;padding:10px 12px;font-weight:600;cursor:pointer}
  .run:disabled{opacity:.6;cursor:not-allowed}
  .kv{display:flex;justify-content:space-between;font-size:12px;color:var(--mute)}
  section.out{padding:14px 18px 22px;overflow:auto}
  .cmd{background:#0b0e14;border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin-bottom:10px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;white-space:pre-wrap;word-break:break-all;color:#cdd3df}
  .meta{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;font-size:12px;color:var(--mute)}
  .meta .chip{background:var(--panel);border:1px solid var(--line);padding:3px 8px;border-radius:999px}
  .cu{color:var(--warn);font-weight:600}
  .verd{font-weight:700}
  pre.out_body{background:#0b0e14;border:1px solid var(--line);border-radius:9px;padding:12px;overflow:auto;margin:0;white-space:pre;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.55;max-height:calc(100vh - 260px)}
  .render{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:10px}
  table.t{border-collapse:collapse;width:100%;font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  table.t th,table.t td{padding:5px 7px;border-bottom:1px dashed var(--line);text-align:right;white-space:nowrap}
  table.t th:first-child,table.t td:first-child,table.t th.sym,table.t td.sym{text-align:left}
  table.t thead th{color:var(--mute);font-weight:500;text-transform:uppercase;font-size:11px;letter-spacing:.3px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#141821}
  table.t tr.click{cursor:pointer}
  table.t tr.click:hover td{background:rgba(106,166,255,.08)}
  .scorebar{display:flex;gap:10px;align-items:center}
  .scorebar .cell{background:#10141c;border:1px solid var(--line);border-radius:9px;padding:7px 10px;min-width:92px;text-align:center}
  .scorebar .cell b{display:block;font-size:17px}
  .scorebar .cell span{color:var(--mute);font-size:11px;letter-spacing:.3px}
  .scorebar .final{background:linear-gradient(180deg,#17203a,#10162a);border-color:var(--accent)}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media (max-width: 1100px){ .grid2{grid-template-columns:1fr} }
  .pillr{display:inline-flex;align-items:center;gap:6px;font-size:12px;background:#10141c;border:1px solid var(--line);border-radius:999px;padding:3px 9px;color:var(--text)}
  .good{color:var(--good)} .warn{color:var(--warn)} .bad{color:var(--bad)}
  .subtle{color:var(--mute)}
  .section-title{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.4px;margin:2px 0 -4px}
  .loading{display:inline-block;animation:spin 1s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .copyrow{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .btn{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:7px;padding:5px 9px;font-size:12px;cursor:pointer}
  .btn:hover{border-color:var(--accent)}
</style>
</head>
<body>
<header>
  <h1>🐦 Birdeye Screener · Test UI</h1>
  <span class="pill" id="cred">loading key…</span>
  <span class="pill" id="ver"></span>
</header>
<main>
  <nav>
    <div class="tabs">
      <div class="tab active" data-tab="tl">Skill #1 · Trending List</div>
      <div class="tab" data-tab="dd">Skill #3 · Token DD</div>
      <div class="tab" data-tab="wa">Skill #14 · Wallet Analysis</div>
      <div class="tab" data-tab="smp">Skill #9 · Smart Money Profile</div>
      <div class="tab" data-tab="junk">Skill #2 · Junk Prediction</div>
    </div>

    <div id="panel-tl" class="group">
      <div class="row"><label>Chain</label>
        <select id="tl_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option></select></div>
      <div class="row"><label>Interval</label>
        <select id="tl_interval"><option>1h</option><option>4h</option><option>24h</option></select></div>
      <div class="row"><label>Source</label>
        <select id="tl_source"><option value="v3-list">v3-list (50 CU · recommended)</option><option value="trending">trending (30 CU · cheaper)</option></select></div>
      <div class="row"><label>Sort by</label>
        <select id="tl_sort"><option>volumeUSD</option><option>market_cap</option><option>liquidity</option><option>trade_count</option><option>holder</option><option>rank</option></select></div>
      <div class="row"><label>Platform</label>
        <select id="tl_platform">
          <option value="">(all)</option>
          <option>pump.fun</option><option>moonshot</option><option>raydium</option>
          <option>jupiter studio</option><option>meteora dbc</option><option>diesel</option>
          <option>gobolt</option><option>bags.fm</option><option>possumlabs</option>
          <option>letsbonk.fun</option><option>meme.com platform</option><option>trix</option>
        </select></div>
      <div class="row"><label>Limit</label>
        <input id="tl_limit" type="text" value="10" /></div>
      <div class="row"><label>Format</label>
        <select id="tl_format"><option value="render">Rendered table (default)</option><option>plain</option><option>telegram</option><option>raw-json</option></select></div>
      <button class="run" id="tl_run">▶ Run Trending List (~50 CU)</button>
    </div>

    <div id="panel-dd" class="group" style="display:none">
      <div class="row"><label>Chain</label>
        <select id="dd_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option></select></div>
      <div class="row"><label>Address</label>
        <input id="dd_address" type="text" placeholder="DaZG1BGU7ZRfoSAy3vWAtMmcMc2sdxcyZuAamxmLjH4" /></div>
      <div class="row"><label>Format</label>
        <select id="dd_format"><option value="render">Rendered scorecard (default)</option><option>plain</option><option>telegram</option><option>raw-json</option></select></div>
      <button class="run" id="dd_run">▶ Run Token DD (~71 CU)</button>
      <button class="run" id="dd_junk" style="margin-top:6px;background:#7c3aed">🗑️ Quick Junk Check (21 CU)</button>
      <div class="kv"><span>Recent (click from Trending)</span><span id="dd_recent" class="subtle">—</span></div>
    </div>

    <div id="panel-wa" class="group" style="display:none">
      <div class="row"><label>Chain</label>
        <select id="wa_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option></select></div>
      <div class="row"><label>Wallet</label>
        <input id="wa_wallet" type="text" placeholder="enter Solana wallet address" /></div>
      <div class="row"><label>Intervals</label>
        <input id="wa_intervals" type="text" value="24h,7d,30d,90d,all" />
        <span class="subtle" style="font-size:10px">comma-sep: 24h,7d,30d,90d,all</span></div>
      <div class="row"><label>PnL method</label>
        <select id="wa_pnl"><option value="wac">wac</option><option value="net_cash">net_cash</option></select></div>
      <div class="row"><label>Skips</label>
        <label class="subtle"><input type="checkbox" id="wa_skip_tx" /> skip tx-list</label>
        <label class="subtle"><input type="checkbox" id="wa_skip_first" /> skip first-funded</label>
        <label class="subtle"><input type="checkbox" id="wa_skip_port" /> skip portfolio</label>
      </div>
      <div class="row"><label>Format</label>
        <select id="wa_format"><option value="render">Rendered (default)</option><option>plain</option><option>telegram</option><option>raw-json</option></select></div>
      <button class="run" id="wa_run">▶ Run Wallet Analysis</button>
      <div class="subtle" style="font-size:10px;margin-top:4px">CU: ~90–180 depending on skips (5× pnl-summary + details + portfolio + tx-list + first-funded)</div>
    </div>

    <div id="panel-smp" class="group" style="display:none">
      <div class="row"><label>Chain</label>
        <select id="smp_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option></select></div>
      <div class="row"><label>Wallet</label>
        <input id="smp_wallet" type="text" placeholder="enter Solana wallet address" /></div>
      <div class="row"><label>PnL method</label>
        <select id="smp_pnl"><option value="wac">wac</option><option value="net_cash">net_cash</option></select></div>
      <div class="row"><label>Skips</label>
        <label class="subtle"><input type="checkbox" id="smp_skip_tx" /> skip tx-list</label>
        <label class="subtle"><input type="checkbox" id="smp_skip_first" /> skip first-funded</label>
      </div>
      <div class="row"><label>Format</label>
        <select id="smp_format"><option value="render">Rendered (default)</option><option>plain</option><option>telegram</option><option>raw-json</option></select></div>
      <button class="run" id="smp_run">▶ Run Smart Money Profile</button>
      <div class="subtle" style="font-size:10px;margin-top:4px">CU: ~90 (7d+30d pnl-summary + details + tx-list + first-funded)</div>
    </div>

    <div id="panel-junk" class="group" style="display:none">
      <div class="row"><label>Chain</label>
        <select id="jk_chain"><option>sol</option><option>bsc</option><option>base</option><option>eth</option></select></div>
      <div class="row" style="align-items:flex-start"><label style="margin-top:6px">Tokens</label>
        <textarea id="jk_tokens" rows="6" style="width:100%;background:#10141c;border:1px solid var(--line);border-radius:7px;padding:8px 9px;outline:none;font-family:ui-monospace,monospace;font-size:12px;color:inherit;resize:vertical" placeholder="comma or newline separated, e.g.&#10;98AG3z...pump&#10;So11111111111111111111111111111111111111112"></textarea></div>
      <div class="row"><label>Threshold</label>
        <span class="subtle" style="font-size:11px">decided by model (lr_params.json)</span></div>
      <div class="row"><label>Format</label>
        <select id="jk_format"><option value="render">Rendered cards (default)</option><option>raw-json</option></select></div>
      <button class="run" id="jk_run">▶ Run Junk Prediction (~21 CU/token)</button>
      <div class="subtle" style="font-size:10px;margin-top:4px">Fetches /defi/token_overview for each token → ML (Logistic Regression, 16 features)</div>

      <div class="section-title" style="margin-top:16px">⚡ Quick Test (1 call · 300 CU)</div>
      <div class="subtle" style="font-size:10px;margin-bottom:8px">Calls /defi/v3/token/list/scroll once (up to 5000 tokens) → random N tokens → ML on list data. No per-token overview.</div>
      <div class="row"><label>Random N</label>
        <input id="jqt_num" type="text" value="30" style="width:80px" /></div>
      <div class="row"><label>Sort by</label>
        <select id="jqt_sortby" style="width:180px"><option value="liquidity">liquidity</option><option value="market_cap">market_cap</option><option value="volume_24h_usd">volume_24h_usd</option><option value="holder">holder</option><option value="recent_listing_time">recent_listing_time</option><option value="last_trade_unix_time">last_trade_unix_time</option></select>
        <select id="jqt_sorttype" style="width:80px"><option value="desc">desc</option><option value="asc">asc</option></select></div>
      <div class="row"><label>Platform</label>
        <select id="jqt_platform"><option value="">(all)</option><option>pump.fun</option><option>moonshot</option><option>raydium</option><option>jupiter studio</option><option>meteora dbc</option><option>diesel</option><option>gobolt</option><option>bags.fm</option><option>possumlabs</option><option>letsbonk.fun</option><option>meme.com platform</option><option>trix</option></select></div>
      <div class="row"><label>Min Liq</label>
        <input id="jqt_minliq" type="text" value="" placeholder="e.g. 1000" style="width:120px" />
        <label style="margin-left:12px">Max Liq</label>
        <input id="jqt_maxliq" type="text" value="" placeholder="e.g. 50000" style="width:120px" /></div>
      <div class="row"><label>Min MC</label>
        <input id="jqt_minmc" type="text" value="" placeholder="e.g. 100000" style="width:120px" />
        <label style="margin-left:12px">Max MC</label>
        <input id="jqt_maxmc" type="text" value="" placeholder="e.g. 5000000" style="width:120px" /></div>
      <button class="run" id="jqt_run" style="background:#7c3aed">🎲 Quick Test — random N / 5000 tokens (300 CU)</button>
    </div>

    <div class="group">
      <div class="section-title">Quick tests</div>
      <div class="copyrow">
        <button class="btn" data-quick="hot">Trending SOL 1h</button>
        <button class="btn" data-quick="pump">Pump.fun hot</button>
        <button class="btn" data-quick="hee">DD · HeeHaw</button>
        <button class="btn" data-quick="spcx">DD · SPCX (SM #1)</button>
      </div>
    </div>
  </nav>

  <section class="out">
    <div id="out"></div>
  </section>
</main>
<script>
const $ = id => document.getElementById(id);

function setTab(t){
  document.querySelectorAll('.tab').forEach(el=>el.classList.toggle('active', el.dataset.tab===t));
  $('panel-tl').style.display = t==='tl' ? '' : 'none';
  $('panel-dd').style.display = t==='dd' ? '' : 'none';
  $('panel-wa').style.display = t==='wa' ? '' : 'none';
  $('panel-smp').style.display = t==='smp' ? '' : 'none';
  $('panel-junk').style.display = t==='junk' ? '' : 'none';
}
document.querySelectorAll('.tab').forEach(el=>el.onclick=()=>setTab(el.dataset.tab));

async function api(script, argv){
  const res = await fetch('/api/run', {
    method:'POST',
    headers:{'content-type':'application/json'},
    body: JSON.stringify({script, argv})
  });
  return res.json();
}

function cmdText(script, argv){
  const base = script==='birdeye_cli' ? 'python3 scripts/birdeye_cli.py'
    : script==='birdeye_screener' ? 'python3 scripts/birdeye_screener.py'
    : 'python3 scripts/birdeye_trending_simple.py';
  return base + ' ' + argv.map(a=>/^[A-Za-z0-9_=-]+$/.test(a)?a:JSON.stringify(a)).join(' ');
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
  const n=Number(v); const s = (n>=0?'+':'') + n.toFixed(1) + '%';
  return s;
}
function add$Label(v){ if(v===null||v===undefined||String(v).trim()===''||String(v)==='N/A') return 'N/A'; const s = fmtUsd(v); return (Number(v)<0?'-':'') + '$' + s.replace('-',''); }
function addrCut(a,head=6,tail=4){ if(!a) return ''; if(a.length<=head+tail+3) return a; return a.slice(0,head)+'…'+a.slice(-tail); }

function copyText(t){ navigator.clipboard?.writeText(t); }

function makeTrendRender(payload){
  // CLI raw-json uses `rows` field; accept either
  const items = Array.isArray(payload?.rows)?payload.rows
    : Array.isArray(payload?.items)?payload.items:[];
  if(!items.length){
    return '<div class="render"><div>No items returned.</div></div>';
  }
  const hasTrades = items.some(x=>x.tradeInterval!=null && x.tradeInterval!==undefined && String(x.tradeInterval)!=='')
    || items.some(x=>x.trade_interval_count!=null || x.tradeIntervalCount!=null || x.trade_count!=null);
  const hasHolders = items.some(x=>x.holderCount!=null && x.holderCount!==undefined && String(x.holderCount)!=='')
    || items.some(x=>x.holder_count!=null || x.holderCount!=null);
  // field mapper: accept both camelCase snake_case from CLI raw-json
  const rowMap = (it)=>({
    address: it.address, symbol: it.symbol || it.Symbol || '?',
    marketCap: it.marketCap ?? it.marketcap_usd ?? it.market_cap,
    liquidity: it.liquidity ?? it.liquidity_usd ?? it.liquidity,
    volInterval: it.volInterval ?? it.volume_interval_usd ?? it.volume_interval ?? it.volume,
    volChangePct: it.volChangePct ?? it.volume_interval_change_pct ?? it.volume_change_pct ?? it.vol_change_pct,
    priceChangePct: it.priceChangePct ?? it.price_interval_change_pct ?? it.price_change_pct,
    tradeInterval: it.tradeInterval ?? it.trade_interval_count ?? it.trade_count ?? it.trades,
    holderCount: it.holderCount ?? it.holder_count ?? it.holders,
  });
  const head = `
    <div class="render">
      <div>
        <div class="section-title">Trending · ${(payload.chain||payload.sourceChain||'').toUpperCase()} · ${payload.interval||payload.timeInterval||''}</div>
        <div class="copyrow" style="margin-top:4px">
          ${items.slice(0,5).map(it0=>{const it=rowMap(it0); return `<button class="btn" data-jump='${JSON.stringify({addr:it.address,sym:it.symbol,chain:payload.chain||'sol'})}'>${htmlEscape(it.symbol||'?')} · ${addrCut(it.address,4,4)}</button>`;}).join('')}
        </div>
      </div>
      <table class="t">
        <thead><tr>
          <th>#</th><th class="sym">Symbol</th><th>MC</th><th>LIQ</th><th>Vol</th><th>ΔVol%</th><th>ΔP%</th>
          ${hasTrades?'<th>Trades</th>':''}${hasHolders?'<th>Holders</th>':''}
        </tr></thead>
        <tbody>
          ${items.map((it0,i)=>{
            const it = rowMap(it0);
            const dp = Number(it.priceChangePct); const dv = Number(it.volChangePct);
            return `<tr class="click" data-jump='${JSON.stringify({addr:it.address,sym:it.symbol,chain:payload.chain||'sol'})}'>
              <td>${i+1}</td>
              <td class="sym">${htmlEscape(it.symbol||'?')}<div class="subtle" style="font-size:11px">${addrCut(it.address||'')}</div></td>
              <td>${add$Label(it.marketCap)}</td>
              <td>${add$Label(it.liquidity)}</td>
              <td>${add$Label(it.volInterval)}</td>
              <td class="${dv>=0?'good':'bad'}">${fmtPctSigned(dv)}</td>
              <td class="${dp>=0?'good':'bad'}">${fmtPctSigned(dp)}</td>
              ${hasTrades?`<td>${it.tradeInterval==null||it.tradeInterval===''?'N/A':Number(it.tradeInterval).toLocaleString()}</td>`:''}
              ${hasHolders?`<td>${it.holderCount==null||it.holderCount===''?'N/A':Number(it.holderCount).toLocaleString()}</td>`:''}
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
  return head;
}

function parseRiskPct(s){
  if(!s) return null;
  const m = /(-?[\d.]+)\s*%/.exec(s); return m?parseFloat(m[1]):null;
}

function parseScoreLine(line){
  // e.g. SCORES   SEC 10.0/10   SMKT 5.0/10   ACT 6.0/10   VOL 8.0/10  →  ⭐ FINAL 7.3/10
  const out = {};
  for(const k of ['SEC','SMKT','ACT','VOL','FINAL']){
    const re = new RegExp(k+'\\s+([\\d.]+)\\s*/\\s*10');
    const m = re.exec(line); if(m) out[k.toLowerCase()] = parseFloat(m[1]);
  }
  return out;
}

function makeDDRender(payload, stdout){
  const lines = (stdout||'').split(/\r?\n/);
  const state = {header:[], risk:[], priceLine:'', bsh:null, sm:null, score:null, verdict:null, footers:[], gaps:null};
  let cur = null;
  for(const line of lines){
    const t = line.trim();
    if(t.startsWith('---')) continue;
    if(t.startsWith('🛡') || /^\s*(SOL|BSC|BASE|ETH)\b/i.test(line) && line.includes('$') && !state.header.length){
      state.header.push(line); continue;
    }
    if(t.toUpperCase().startsWith('RISK / SECURITY')){ cur='risk'; continue; }
    if(t.toUpperCase().startsWith('PRICE ACTION')){ cur='price'; continue; }
    if(t.toUpperCase().startsWith('BUY/SELL')){ cur='bs'; state.bsh = {head:null,rows:[]}; continue; }
    if(t.toUpperCase().startsWith('SMART MONEY')){ cur='sm'; continue; }
    if(t.startsWith('SCORES') || t.includes('⭐ FINAL')){ state.score = parseScoreLine(line); }
    if(t.startsWith('VERDICT:')){ state.verdict = t.replace(/^VERDICT:\s*/,''); }
    if(t.startsWith('⚡CU:') || t.startsWith('⚠ ') || t.startsWith('✅ ')){ state.footers.push(line); continue; }
    if(cur==='risk' && t){ state.risk.push(t); }
    if(cur==='price' && /5m/.test(t) && /24h/.test(t)){ state.priceLine = t; }
    if(cur==='bs' && t){
      if(/^win\s/.test(t)){ state.bsh.head = t; }
      else if(/^\s*(5m|15m|30m|1h|2h|4h|8h|24h)\s/.test(t)){ state.bsh.rows.push(t); }
    }
    if(cur==='sm' && t){ state.sm = (state.sm? state.sm+'\n  ':'') + t; }
  }
  // Render
  const sec = (n)=>`<div class="cell"><b>${Number(n||0).toFixed(1)}/10</b><span>SEC</span></div>`;
  const smkt = (n)=>`<div class="cell"><b>${Number(n||0).toFixed(1)}/10</b><span>SMKT</span></div>`;
  const act = (n)=>`<div class="cell"><b>${Number(n||0).toFixed(1)}/10</b><span>ACT</span></div>`;
  const vol = (n)=>`<div class="cell"><b>${Number(n||0).toFixed(1)}/10</b><span>VOL</span></div>`;
  const fin = (n)=>`<div class="cell final"><b>${Number(n||0).toFixed(1)}/10</b><span>FINAL</span></div>`;
  const vclass = (v)=>(/STRONG BUY|BUY/.test(v||'')?'good':/AVOID|SELL/.test(v||'')?'bad':'warn');
  const riskRow = line => {
    let cls = 'subtle';
    if(/🔴/.test(line)) cls='bad';
    else if(/⚠/.test(line)) cls='warn';
    else if(/✅/.test(line)) cls='good';
    return `<div class="pillr"><span class="${cls}">${htmlEscape(line)}</span></div>`;
  };
  const bsTable = (bsh)=>{
    if(!bsh||!bsh.rows.length) return '';
    const head = bsh.head || 'win        Vol$       Buy$      Sell$    B%    Buys   Sells  TradeB%   Wallets    NetFlow$';
    const col = 'Vol$ Buy$ Sell$ B% Buys Sells TradeB% Wallets NetFlow$'.split(' ');
    return `<div>
      <div class="section-title">Buy/Sell + Money Flow</div>
      <table class="t" style="margin-top:6px">
        <thead><tr><th class="sym">win</th>${col.map(c=>`<th>${c}</th>`).join('')}</tr></thead>
        <tbody>
          ${bsh.rows.map(row=>{
            const bits = row.trim().split(/\s+/);
            // first token = win, then 9 values roughly in order
            const [win, ...rest] = bits;
            const pad = (n,v='')=>`<td>${htmlEscape(rest[n-1]||v)}</td>`;
            return `<tr><td class="sym">${htmlEscape(win||'')}</td>${pad(1)}${pad(2)}${pad(3)}${pad(4)}${pad(5)}${pad(6)}${pad(7)}${pad(8)}${pad(9,'')}</tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
  };
  const headerBlock = state.header.map(l=>`<div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px">${htmlEscape(l)}</div>`).join('');
  return `<div class="render">
    ${headerBlock}
    <div><div class="section-title">Risk / Security</div>
      <div class="copyrow" style="margin-top:6px">${state.risk.map(riskRow).join('') || '<span class="subtle">—</span>'}</div>
    </div>
    <div><div class="section-title">Price Δ%</div>
      <div style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;margin-top:6px">${htmlEscape(state.priceLine||'—')}</div>
    </div>
    ${bsTable(state.bsh)}
    <div><div class="section-title">Smart Money</div>
      <div style="margin-top:6px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px">${htmlEscape(state.sm||'—')}</div>
    </div>
    <div class="scorebar">
      ${state.score ? sec(state.score.sec)+smkt(state.score.smkt)+act(state.score.act)+vol(state.score.vol)+fin(state.score.final) : '<span class="subtle">scores unavailable</span>'}
    </div>
    ${state.verdict ? `<div>Verdict: <span class="verd ${vclass(state.verdict)}">${htmlEscape(state.verdict)}</span></div>`:''}
    <div class="meta">${state.footers.map(f=>`<span class="chip">${htmlEscape(f)}</span>`).join('')}</div>
  </div>`;
}

function htmlEscape(s){ return String(s).replace(/[&<>]/g, c=> ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function attachJumps(root){
  root.querySelectorAll('[data-jump]').forEach(el=>{
    el.onclick = () => {
      const o = JSON.parse(el.getAttribute('data-jump'));
      $('dd_address').value = o.addr || '';
      $('dd_chain').value = o.chain || 'sol';
      const prev = $('dd_recent').textContent === '—' ? '' : $('dd_recent').textContent + ' · ';
      $('dd_recent').textContent = prev + (o.sym||'?')+':'+addrCut(o.addr||'',4,4);
      setTab('dd');
    };
  });
}

async function runCLI(side, {formatOverride=null}={}){
  const out = $('out');
  out.innerHTML = `<div class="render"><div><span class="loading">⟳</span> Running…</div></div>`;

  let script, argv, payloadKey;
  if(side==='tl'){
    script='birdeye_cli';
    const fmtChosen = formatOverride || $('tl_format').value;
    const fmtUse = fmtChosen==='render' ? 'raw-json' : fmtChosen;
    argv=['trending-list','--chain',$('tl_chain').value,'--interval',$('tl_interval').value,
      '--source',$('tl_source').value,'--sort-by',$('tl_sort').value,'--limit',$('tl_limit').value,
      '--format',fmtUse];
    const p = $('tl_platform').value; if(p) argv.push('--platform', p);
    payloadKey = (fmtChosen==='render' ? 'render-tl' : fmtUse);
  }else if(side==='dd'){
    script='birdeye_cli';
    const addr = $('dd_address').value.trim();
    if(!addr){ out.innerHTML=`<div class="render"><div class="bad">Address is required.</div></div>`; return; }
    const fmtChosen = formatOverride || $('dd_format').value;
    const fmtUse = fmtChosen==='render' ? 'plain' : fmtChosen;
    argv=['token-dd','--chain',$('dd_chain').value,'--address',addr,'--format',fmtUse];
    payloadKey = (fmtChosen==='render' ? 'render-dd' : fmtUse);
  }else if(side==='wa'){
    script='birdeye_cli';
    const wallet = $('wa_wallet').value.trim();
    if(!wallet){ out.innerHTML=`<div class="render"><div class="bad">Wallet address is required.</div></div>`; return; }
    const fmtChosen = formatOverride || $('wa_format').value;
    const fmtUse = fmtChosen==='render' ? 'rendered' : fmtChosen;
    argv=['wallet-analysis','--chain',$('wa_chain').value,'--wallet',wallet,
      '--intervals',$('wa_intervals').value||'24h,7d,30d,90d,all',
      '--pnl-method',$('wa_pnl').value,'--format',fmtUse];
    if($('wa_skip_tx').checked) argv.push('--skip-tx-list');
    if($('wa_skip_first').checked) argv.push('--skip-first-tx');
    if($('wa_skip_port').checked) argv.push('--skip-portfolio');
    payloadKey = (fmtChosen==='render' ? 'render-wa' : fmtUse);
  }else if(side==='smp'){
    script='birdeye_cli';
    const wallet = $('smp_wallet').value.trim();
    if(!wallet){ out.innerHTML=`<div class="render"><div class="bad">Wallet address is required.</div></div>`; return; }
    const fmtChosen = formatOverride || $('smp_format').value;
    const fmtUse = fmtChosen==='render' ? 'rendered' : fmtChosen;
    argv=['smart-money-profile','--chain',$('smp_chain').value,'--wallet',wallet,
      '--pnl-method',$('smp_pnl').value,'--format',fmtUse];
    if($('smp_skip_tx').checked) argv.push('--skip-tx-list');
    if($('smp_skip_first').checked) argv.push('--skip-first-tx');
    payloadKey = (fmtChosen==='render' ? 'render-smp' : fmtUse);
  }else if(side==='junk'){
    script='birdeye_cli';
    const tokens = $('jk_tokens').value.trim();
    if(!tokens){ out.innerHTML=`<div class="render"><div class="bad">At least one token address is required.</div></div>`; return; }
    const fmtChosen = formatOverride || $('jk_format').value;
    const fmtUse = fmtChosen==='render' ? 'rendered' : fmtChosen;
    argv=['junk-predict','--chain',$('jk_chain').value,'--tokens',tokens,
      '--format',fmtUse];
    payloadKey = (fmtChosen==='render' ? 'render-junk' : fmtUse);
  }else if(side==='dd-junk'){
    script='birdeye_cli';
    const ddTok = $('dd_address').value.trim();
    if(!ddTok){ out.innerHTML=`<div class="render"><div class="bad">Enter a token address in the DD panel first.</div></div>`; return; }
    argv=['junk-predict','--chain',$('dd_chain').value,'--tokens',ddTok,
      '--format','rendered'];
    payloadKey='render-junk';
  }else if(side==='jqt'){
    script='birdeye_cli';
    argv=['junk-quick-test','--chain',$('jk_chain').value,
      '--num',$('jqt_num').value||'30',
      '--sort-by',$('jqt_sortby').value,
      '--sort-type',$('jqt_sorttype').value];
    const pf=$('jqt_platform').value; if(pf) argv.push('--platform',pf);
    const mnl=$('jqt_minliq').value.trim(); if(mnl) argv.push('--min-liquidity',mnl);
    const mxl=$('jqt_maxliq').value.trim(); if(mxl) argv.push('--max-liquidity',mxl);
    const mnm=$('jqt_minmc').value.trim(); if(mnm) argv.push('--min-market-cap',mnm);
    const mxm=$('jqt_maxmc').value.trim(); if(mxm) argv.push('--max-market-cap',mxm);
    argv.push('--format','rendered');
    payloadKey='render-junk';
  }
  $('out').dataset.lastSide=side; $('out').dataset.lastPayloadKey=payloadKey;
  try{
    const j = await api(script, argv);
    const cmd = cmdText(script, argv);
    let bodyBlock;
    if(payloadKey==='render-tl'){
      let payload = j.stdout;
      try{ payload = JSON.parse(j.stdout); }catch(e){}
      bodyBlock = makeTrendRender(payload) + `<div style="margin-top:10px"><div class="section-title" style="margin-bottom:4px">CLI stdout (raw JSON)</div><pre class="out_body">${htmlEscape(j.stdout||'')}</pre></div>`;
    }else if(payloadKey==='render-dd'){
      let payload = null;
      // try parse JSON if accidentally plain
      try { if(j.stdout && j.stdout.trim().startsWith('{')) payload = JSON.parse(j.stdout); }catch(e){}
      bodyBlock = makeDDRender(payload, j.stdout);
    }else if(payloadKey==='render-wa' || payloadKey==='render-smp' || payloadKey==='render-junk'){
      // CLI rendered output: first line is #RUN_ID prefix, rest is a JSON envelope with `html`.
      const raw = j.stdout || '';
      const nl = raw.indexOf('\n');
      const jsonStr = nl>=0 ? raw.slice(nl+1) : raw;
      let envelope = null, runLine = '';
      if(nl>=0) runLine = raw.slice(0, nl);
      try { envelope = JSON.parse(jsonStr.trim()); }catch(e){}
      const htmlOut = (envelope && envelope.html) ? envelope.html : `<pre class="out_body">${htmlEscape(raw)}</pre>`;
      bodyBlock = `<div class="render">${htmlOut}</div>` +
        (runLine ? `<div style="margin-top:8px;font-size:10px;color:var(--mute);font-family:ui-monospace,monospace">${htmlEscape(runLine)}</div>` : '');
    }else{
      bodyBlock = `<pre class="out_body">${htmlEscape(j.stdout||'')}${j.stderr?`\n\n---- stderr ----\n${htmlEscape(j.stderr)}`:''}</pre>`;
    }
    out.innerHTML = `
      <div class="cmd">${htmlEscape(cmd)}</div>
      <div class="meta">
        <span class="chip">exit: ${j.exit}</span>
        <span class="chip">${j.stderr?'stderr':''}</span>
        <span class="chip">${j.duration_ms ?? '?'} ms</span>
        <span class="chip cu">CU estimate · see footer inside output</span>
      </div>
      ${bodyBlock}
    `;
    attachJumps(out);
  }catch(e){
    out.innerHTML = `<div class="render"><div class="bad">Error: ${htmlEscape(e.message||String(e))}</div></div>`;
  }
}

$('tl_run').onclick = ()=>runCLI('tl');
$('dd_run').onclick = ()=>runCLI('dd');
$('wa_run').onclick = ()=>runCLI('wa');
$smp_run = $('smp_run'); if($smp_run) $smp_run.onclick = ()=>runCLI('smp');
$jk_run = $('jk_run'); if($jk_run) $jk_run.onclick = ()=>runCLI('junk');
$dd_junk = $('dd_junk'); if($dd_junk) $dd_junk.onclick = ()=>runCLI('dd-junk');
$jqt_run = $('jqt_run'); if($jqt_run) $jqt_run.onclick = ()=>runCLI('jqt');

// Copy-to-clipboard for wallet/token addresses in rendered output
document.addEventListener('click', (e)=>{
  const el = e.target.closest('[data-copy-addr]');
  if(el){
    const v = el.getAttribute('data-copy-addr') || el.textContent || '';
    navigator.clipboard?.writeText(v).then(()=>{
      const orig = el.textContent;
      el.textContent = '✓ copied';
      setTimeout(()=>{ el.textContent = orig; }, 1200);
    }).catch(()=>{});
  }
});

document.querySelectorAll('[data-quick]').forEach(b=>{
  b.onclick=()=>{
    const q = b.dataset.quick;
    if(q==='hot'){ setTab('tl'); runCLI('tl'); }
    else if(q==='pump'){ setTab('tl'); $('tl_platform').value='pump.fun'; runCLI('tl'); }
    else if(q==='hee'){
      setTab('dd'); $('dd_chain').value='sol';
      $('dd_address').value='DaZG1BGU7ZRfoSAy3vWAtMmcMc2sdxcyZuAamxmLjH4'; runCLI('dd');
    }else if(q==='spcx'){
      setTab('dd'); $('dd_chain').value='sol';
      $('dd_address').value='SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb'; runCLI('dd');
    }
  };
});

async function credCheck(){
  try{
    const j = await api('birdeye_screener', ['config','--check']);
    const ok = j.exit === 0;
    $('cred').textContent = ok ? '🔑 API key OK' : '🔑 API key NOT SET';
    $('cred').className = 'pill ' + (ok?'':'bad');
    $('ver').textContent = 'UI server · stdlib HTTP';
  }catch(e){ $('cred').textContent='🔑 '+ (e.message||String(e)); }
}
credCheck();
// auto open on first load with trending default
runCLI('tl');
</script>
</body>
</html>
"""


def run_script_argv(script_alias: str, argv: list[str]):
    if script_alias not in ALLOWED_SCRIPTS:
        return {"exit": 2, "stdout": "", "stderr": f"script not allowed: {script_alias}", "duration_ms": 0}
    script_path = ALLOWED_SCRIPTS[script_alias]
    # basic argv safety: no absolute paths, no shell redirects; each token must look like flag or value
    for tok in argv:
        if isinstance(tok, str) and any(c in tok for c in ";&|`$<>\\'\""):
            return {"exit": 2, "stdout": "", "stderr": f"invalid token: {tok!r}", "duration_ms": 0}
    cmd = [PY, script_path, *argv]
    t0 = __import__("time").perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=180,
            env={**os.environ},
        )
        dur = int((__import__("time").perf_counter() - t0) * 1000)
        return {
            "exit": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": dur,
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "", "stderr": "timeout 180s", "duration_ms": 180000, "cmd": cmd}
    except Exception as e:
        return {"exit": 1, "stdout": "", "stderr": str(e), "duration_ms": 0, "cmd": cmd}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BirdeyeUI/1.0"

    def log_message(self, fmt, *args):  # quieter
        sys.stderr.write("[UI] " + (fmt % args) + "\n")

    def _send_json(self, code: int, obj: dict):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code: int, html_bytes: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html_bytes)

    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html(200, UI_HTML.encode("utf-8"))
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "cwd": str(ROOT)})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/run":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._send_json(400, {"error": f"bad json: {e}"})
                return
            script = body.get("script") or "birdeye_cli"
            argv = body.get("argv") or []
            if not isinstance(argv, list):
                self._send_json(400, {"error": "argv must be list"})
                return
            res = run_script_argv(script, [str(a) for a in argv])
            self._send_json(200, res)
            return
        self._send_json(404, {"error": "not found"})


def serve(port: int, host: str = "127.0.0.1"):
    srv = http.server.HTTPServer((host, port), Handler)
    sys.stderr.write(f"[UI] Birdeye Screener Test UI → http://{host}:{port}\n")
    sys.stderr.write(f"[UI] Scripts dir: {SCRIPTS}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[UI] stopped by user.\n")
        srv.server_close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    args = ap.parse_args()
    serve(args.port, args.host)


if __name__ == "__main__":
    main()
