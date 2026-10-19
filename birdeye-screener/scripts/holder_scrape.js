#!/usr/bin/env node
/**
 * Skill #6 (Spam Token Cleaner) — Step 2: Holder concentration scraper.
 *
 * Bypasses Birdeye paid holder/holder-profile API endpoints
 * (30-21 CU / token) by scraping birdeye.so holders tab via
 * headless Chrome + puppeteer-core.
 *
 * Input (stdin, single-line JSON array):
 *   [ { "chain": "solana", "address": "Pren1...Lkhw", "market_cap": 1234 }, ... ]
 *
 * Output (stdout, newline-delimited JSON):
 *   { idx, top10_holding_pct, top1_address, top1_amount, top1_pct, top_wallet_value, ok, note }
 *   per input token, emitted as it completes.
 *
 * Final single line JSON on stdout close: { scraped: N, failed: K, total: M }
 */
'use strict';
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const os = require('os');

const CHROME_EXEC_CANDIDATES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  process.env.PUPPETEER_EXECUTABLE_PATH || '',
].filter(Boolean);

function findChrome() {
  for (const p of CHROME_EXEC_CANDIDATES) {
    try { if (fs.existsSync(p)) return p; } catch (_) {}
  }
  return null;
}

function moneyParse(s) {
  if (s == null) return null;
  s = String(s).trim().replace(/,/g, '').replace(/\s+/g, ' ');
  if (!s) return null;
  // Handle ($1.5M) parentheses for negatives
  let sign = 1;
  if (s.startsWith('(') && s.endsWith(')')) { s = s.slice(1, -1); sign = -1; }
  if (s.startsWith('-')) { sign = -1; s = s.slice(1); }
  if (s.startsWith('+')) { s = s.slice(1); }
  let mult = 1;
  const m = s.match(/^([\d.]+)\s*([BMK%])?/i);
  if (!m) return null;
  let n = parseFloat(m[1]);
  if (isNaN(n)) return null;
  const suf = (m[2] || '').toUpperCase();
  if (suf === 'B') mult = 1e9;
  else if (suf === 'M') mult = 1e6;
  else if (suf === 'K') mult = 1e3;
  return sign * n * mult;
}

function extractWalletFromHref(href) {
  if (!href) return '';
  const m = href.match(/\/wallet-analyzer\/([^/?#]+)/i);
  if (m && m[1]) return decodeURIComponent(m[1]);
  const m2 = href.match(/\/(?:token|address|account|wallet)\/([^/?#]+)/i);
  if (m2 && m2[1]) return decodeURIComponent(m2[1]);
  return '';
}

async function extractFromPage(page, tokenObj) {
  const chain = tokenObj.chain || 'solana';
  const chainShort = ({solana:'sol', ethereum:'eth', arbitrum:'arc', base:'base', bsc:'bsc', robinhood:'rh'})[chain] || String(chain).toLowerCase().replace(/[^a-z]/g,'').slice(0,6);
  const addr = tokenObj.address || '';
  // Try both URL layouts: /chain/token/<addr>?tab=holders (old) vs /token/<addr>?chain=<slug>&tab=holders (new Birdeye rewrite)
  const urlAlt = [
    `https://birdeye.so/token/${encodeURIComponent(addr)}?chain=${encodeURIComponent(chain)}&tab=holders&trades_layout=table`,
    `https://birdeye.so/token/${encodeURIComponent(addr)}?chain=${encodeURIComponent(chainShort)}&tab=holders&trades_layout=table`,
    `https://birdeye.so/${encodeURIComponent(chain)}/token/${encodeURIComponent(addr)}?tab=holders&trades_layout=table`,
    `https://birdeye.so/${encodeURIComponent(chainShort)}/token/${encodeURIComponent(addr)}?tab=holders&trades_layout=table`,
  ];
  let httpStatus = 0, sniff = null;
  for (let attempt = 0; attempt < urlAlt.length; attempt++) {
    const url = urlAlt[attempt];
    try {
      const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
      httpStatus = resp && resp.status ? resp.status() : 0;
      await new Promise(r => setTimeout(r, 1200));
      // Try click Holders tab button if not auto-switched (React lazy hydration)
      try {
        const tabSel = 'button[role="tab"], a[href*="holders"], .tab-bar .tab, [class*="tab"] span, [data-testid="holders-tab"], [id*="holders"]';
        await page.evaluate(function (sel) {
          var btns = Array.from(document.querySelectorAll(sel));
          for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText || btns[i].textContent || '').replace(/\s+/g, ' ').trim();
            if (/^Holders(\s|\(|$)/i.test(t) || /Holder/i.test(t) && t.length < 20) { try { btns[i].click(); return; } catch(_){} }
          }
        }, tabSel);
        await new Promise(r => setTimeout(r, 700));
      } catch (_) {}
      // Try waitForSelector for <table> with rows
      try { await page.waitForSelector('table tr', { timeout: 6000 }); } catch (_) {}
      let waited = 0, found = false;
      while (waited < 16000) {
        sniff = await page.evaluate(function () {
          var bt = (document.body && document.body.innerText) || '';
          var t10 = bt.match(/Top\s*10\s*Holding\s*:\s*([\d.]+)\s*%/i);
          var trCount = document.querySelectorAll('table tr').length;
          var headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,button[role="tab"], [class*="Tab"] span')).slice(0,20).map(x=>(x.innerText||'').replace(/\s+/g,' ').trim()).filter(Boolean);
          var cf = bt.indexOf('Checking your browser') >= 0 || bt.indexOf('Cloudflare') >= 0 || bt.indexOf('Enable JavaScript') >= 0 || bt.indexOf('Attention Required') >= 0;
          var notFound = (bt.indexOf('not found')>=0 && bt.length < 3000) || false;
          return { bodyLen: bt.length, hasTop10: !!t10, top10Raw: t10 ? t10[1] : null, trCount: trCount, head: headings, pageTitle: (document.title || '').slice(0, 120), cf: cf, nf: notFound, bodyHead: bt.slice(0, 500) };
        });
        if (sniff.cf || httpStatus >= 400 || sniff.nf) { break; }
        if (sniff.hasTop10 && sniff.trCount >= 2) { found = true; break; }
        if (sniff.bodyLen > 5000 && sniff.trCount >= 2) { found = true; break; }
        if (sniff.bodyLen < 800 && waited > 5000) break;
        await new Promise(r => setTimeout(r, 700)); waited += 700;
      }
      if (found) break;
      // Don't continue to next URL if we got actual 200 non-CF page with content but no top10 text (old UI layout)
      if (!sniff.cf && httpStatus === 200 && sniff && sniff.bodyLen > 3000) {
        break;
      }
    } catch (pageErr) {
      process.stderr.write(`[scrape][${addr.slice(0, 8)}…] URL attempt ${attempt} fail: ${String(pageErr.message||pageErr).slice(0,120)}\n`);
    }
  }
  if (!sniff || !(sniff.hasTop10 || sniff.trCount >= 2 || (sniff.bodyLen||0) > 3000)) {
    process.stderr.write(`[scrape][${addr.slice(0, 8)}…] abort; no content loaded. status=${httpStatus} CF=${sniff?sniff.cf:'—'} bodyLen=${sniff?sniff.bodyLen:0} title=${sniff?sniff.pageTitle:'—'} head=${JSON.stringify(sniff?sniff.head:[])}\n`);
    if (sniff && sniff.bodyHead) process.stderr.write(`[scrape][${addr.slice(0,8)}…] bodyHead 500c=${JSON.stringify(sniff.bodyHead)}\n`);
  }
  const res = await page.evaluate(function extract() {
    var bodyT = (document.body && document.body.innerText) || '';
    var top10m = bodyT.match(/Top\s*10\s*Holding\s*:\s*([\d.]+)\s*%/i);
    var top10Pct = top10m ? parseFloat(top10m[1]) : null;
    var trs = document.querySelectorAll('table tr');
    var rowCells = null, ri = -1;
    for (var i = 1; i < Math.min(trs.length, 25); i++) {
      var cells = trs[i].querySelectorAll('td');
      if (cells.length >= 6) { rowCells = cells; ri = i; break; }
    }
    var firstWalletAddr = '', walletShort = '', walletLabel = '';
    var cellTexts = [], cellHrefs = [];
    if (rowCells) {
      var c1 = rowCells[1] || rowCells[0];
      if (c1) {
        walletLabel = (c1.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80);
        var a = c1.querySelector('a[href*="wallet-analyzer"], a[href*="/wallet/"], a[href*="/account/"]') || c1.querySelector('a[href]');
        if (a) firstWalletAddr = a.getAttribute('href') || '';
      }
      for (var j = 0; j < Math.min(rowCells.length, 40); j++) {
        cellTexts.push((rowCells[j].innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200));
        var aa = rowCells[j].querySelector('a[href*="wallet-analyzer"], a[href*="/wallet/"], a[href*="/account/"]') || rowCells[j].querySelector('a[href]');
        cellHrefs.push(aa ? aa.getAttribute('href') || '' : '');
        if (aa && !firstWalletAddr) firstWalletAddr = aa.getAttribute('href') || '';
      }
      // short-address detection: cell matching xxx...xxx truncated wallet pattern
      // used as anchor: 3 cells before = $USD | Pct% | TokenAmount
      var solPat = /^[1-9A-HJ-NP-Za-km-z]{6,}\.\.\.[A-Za-z0-9]{3,}$/;
      var evmPat = /^0x[a-fA-F0-9]{4,}\.\.\.[a-fA-F0-9]{3,}$/;
      for (var k = 0; k < cellTexts.length; k++) {
        var t = cellTexts[k].split(/\s+/)[0] || '';
        if (solPat.test(t) || evmPat.test(t)) { walletShort = t; break; }
      }
    }
    return {
      top10Pct: top10Pct,
      walletHref: firstWalletAddr,
      walletLabel: walletLabel,
      walletShort: walletShort,
      cells: cellTexts,
      cellHrefs: cellHrefs,
      rowIdx: ri
    };
  });
  const result = {
    top10_holding_pct: res.top10Pct,
    top1_address: extractWalletFromHref(res.walletHref) || res.walletLabel || res.walletShort || '',
    _wallet_label: res.walletLabel,
    _wallet_short: res.walletShort,
  };
  // User rule: "chính là cột remaining đó có % value và amount lấy các cái đó"
  // Scan tail cells right-to-left for the HOLD% (no +/- sign) then find adjacent $USD and TOKEN AMOUNT.
  const cells = res.cells || [];
  // Focus on last 12 cells only (skip earlier Bought/Sold/PnL columns)
  const tailCells = cells.length > 12 ? cells.slice(cells.length - 12) : cells.slice();
  const offset = cells.length - tailCells.length;
  let pctIdx = -1, usdIdx = -1, amtIdx = -1;
  for (let k = tailCells.length - 1; k >= 2; k--) {
    const tPct = (tailCells[k] || '').trim();
    if (/^\d+(?:\.\d+)?\s*%$/.test(tPct) && !tPct.includes('+') && !tPct.includes('-') && !tPct.includes('(')) {
      pctIdx = k;
      // Prefer the USD cell: look 1–3 positions before pct cell in tailCells, must start with $
      for (let d = 1; d <= 3 && pctIdx - d >= 0; d++) {
        const cand = tailCells[pctIdx - d].trim();
        if (/^\(?\$[\d.,]+[BMK]?\)?/.test(cand)) { usdIdx = pctIdx - d; break; }
      }
      // Amount cell: digits [0-9.,] + optional B/M/K suffix, start with digit
      for (let d = 1; d <= 4 && pctIdx - d >= 0; d++) {
        if (pctIdx - d === usdIdx) continue;
        const cand = tailCells[pctIdx - d].trim();
        if (/^\d[\d.,]*\s*[BMK]?$/.test(cand)) { amtIdx = pctIdx - d; break; }
      }
      // If amt not found or usd not found try swap order — search after pctIdx (some layouts swap USD|amt)
      if (amtIdx === -1) {
        for (let d = 1; d <= 3 && pctIdx + d < tailCells.length; d++) {
          const cand = tailCells[pctIdx + d].trim();
          if (/^\d[\d.,]*\s*[BMK]?$/.test(cand)) { amtIdx = pctIdx + d; break; }
        }
      }
      if (usdIdx === -1) {
          for (let d = 1; d <= 3 && pctIdx + d < tailCells.length; d++) {
            if (pctIdx + d === amtIdx) continue;
            const cand = tailCells[pctIdx + d].trim();
            if (/^\(?\$[\d.,]+[BMK]?\)?/.test(cand)) { usdIdx = pctIdx + d; break; }
          }
      }
      if (pctIdx !== -1) break;
    }
  }
  let usdPart = usdIdx !== -1 ? tailCells[usdIdx] : null;
  let pctPart = pctIdx !== -1 ? tailCells[pctIdx] : null;
  let amtPart = amtIdx !== -1 ? tailCells[amtIdx] : null;
  // Multi-cell fallback: scan whole row for a Remaining-style 3-in-1 blob (e.g. "$1.57M 19.18% 1.47K")
  if (!pctPart || !usdPart || !amtPart) {
    for (let i = 0; i < cells.length; i++) {
      const s = cells[i] || '';
      const m = s.match(/(\(?\$[0-9.,]+[BMK]?\)?)\s+([0-9.]+%)\s+([0-9.,]+[BMK]?)/);
      if (m) { usdPart = usdPart || m[1]; pctPart = pctPart || m[2]; amtPart = amtPart || m[3]; }
    }
  }
  const globalUsd = usdIdx !== -1 ? usdIdx + offset : -1;
  const globalPct = pctIdx !== -1 ? pctIdx + offset : -1;
  const globalAmt = amtIdx !== -1 ? amtIdx + offset : -1;
  process.stderr.write(`[scrape:${(tokenObj.address||'').slice(0,8)}…] tail=${tailCells.length} cells=${cells.length} USD#${globalUsd}=${usdPart||''} PCT#${globalPct}=${pctPart||''} AMT#${globalAmt}=${amtPart||''}\n`);
  if (cells.length) {
    process.stderr.write(`[scrape:${(tokenObj.address||'').slice(0,8)}…] cells=[\n  ${tailCells.join('\n  ')}\n]\n`);
  }
  const top1_amount = moneyParse(amtPart);
  let top1_pct = null;
  if (pctPart) {
    top1_pct = parseFloat(String(pctPart).replace('%', ''));
    if (!isNaN(top1_pct)) result.top1_pct = top1_pct;
  }
  if (top1_amount != null) result.top1_amount = top1_amount;
  const mcUsd = typeof tokenObj.market_cap === 'number' ? tokenObj.market_cap : moneyParse(tokenObj.market_cap || '');
  if (top1_pct != null && typeof mcUsd === 'number' && !isNaN(mcUsd)) {
    result.top_wallet_value = (top1_pct / 100.0) * mcUsd;
  } else if (usdPart) {
    result.top_wallet_value = moneyParse(usdPart);
  }
  const okOk = !!(result.top10_holding_pct != null || (result.top1_address && result.top1_amount != null) || result.top1_pct != null);
  return { ok: okOk, ...result };
}

async function main() {
  const exe = findChrome();
  if (!exe) {
    process.stderr.write('ERR: cannot find Chrome binary. Set PUPPETEER_EXECUTABLE_PATH env var or install Chrome.\n');
    process.exit(2);
  }
  const stdinBuf = fs.readFileSync(0, 'utf8').trim();
  let input = [];
  try { input = JSON.parse(stdinBuf); } catch (e) {
    process.stderr.write('ERR: invalid stdin JSON array: ' + e.message + '\n');
    process.exit(2);
  }
  if (!Array.isArray(input)) {
    process.stderr.write('ERR: stdin must be JSON array of {chain, address, market_cap?}.\n');
    process.exit(2);
  }
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'birdeye-stc-'));
  // BLOCK GoogleSoftwareUpdate / GoogleUpdater / Keystone registration spawns.
  // Eliminates macOS Gatekeeper popup "Apple could not verify GoogleUpdater is free of malware"
  // every time Chrome is launched via puppeteer.
  process.env.GOOGLE_CHROME_DISABLE_SOFTWARE_UPDATE = '1';
  process.env.KS_PRODUCT_SHOULD_UPDATE = '0';
  process.env.KEYSTONE_SHOULD_UPDATE = '0';
  process.env.CHROME_VERSION_SPECIFIC_KEEP = '1';
  // Point Keystone registration path inside temp profile (harmless no-op if missing).
  process.env.KSREGISTRATION_PATH = path.join(userDataDir, 'KSRegistration');
  const headless = process.env.HEADLESS === '0' || process.env.HEADLESS === 'false'
    ? false
    : (process.env.HEADLESS === 'old' ? true : 'new');
  process.stderr.write(`[scrape] launching Chrome headless=${String(headless)} profile=${userDataDir}\n`);
  const browser = await puppeteer.launch({
    executablePath: exe,
    headless: headless,
    userDataDir,
    ignoreDefaultArgs: [
      '--disable-background-networking', // keep networking for birdeye page load
    ],
    args: [
      // Core sandbox/render
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu',
      '--disable-dev-shm-usage', '--hide-scrollbars', '--mute-audio',
      '--in-process-gpu', '--disable-backgrounding-occluded-windows',
      '--disable-blink-features=AutomationControlled',
      // DISABLE GOOGLE AUTO-UPDATE / KEYSTONE / GOOGLEUPDATER SPAWNS (macOS Gatekeeper popup killer)
      '--disable-background-networking',
      '--disable-component-extensions-with-background-pages',
      '--disable-default-apps',
      '--disable-extensions',
      '--disable-features=ChromeWhatsNewUI,MediaRouter,Translate,BraveSearchUpdate,GoogleUpdate,OnDeviceHeadSuggest,BackendFetch,BackgroundFetch,ServiceWorker,NavigationPredictor',
      '--disable-sync',
      '--disable-background-downloads',
      '--no-default-browser-check',
      '--no-first-run',
      '--no-pings',
      '--safebrowsing-disable-auto-update',
      '--simulate-outdated-no-au',
      '--component-updater=url-source=http://localhost:0',
      '--disable-cloud-policy-on-login',
      '--no-service-autorun',
      '--disable-logging',
      '--log-level=3',
      // Disable writes to RLZ flockfile / GoogleUpdater log paths that trigger TRAE sandbox restriction
      '--disable-rlz',
      '--disable-rlz-branding',
      '--metrics-recording-only',
      '--disable-breakpad',
      '--disable-backing-store-limit',
    ],
    defaultViewport: { width: 1600, height: 1100 },
    // Suppress any permission / dialog prompt before it appears
    handleSIGINT: true, handleSIGTERM: true, handleSIGHUP: true,
  });
  // Dismiss any page-level JS dialogs (alert/prompt/confirm) automatically
  const autoDismissPage = async (page) => {
    page.on('dialog', async (d) => { try { await d.dismiss(); } catch(_) {} });
    page.on('error', (_) => {});
    page.on('pageerror', (_) => {});
  };
  const context = browser.defaultBrowserContext();
  try { await context.overridePermissions('https://birdeye.so', []); } catch(_) {}
  const page = await browser.newPage();
  await autoDismissPage(page);
  try { await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'); } catch(_) {}
  await page.setExtraHTTPHeaders({ 'Accept-Language': 'en-US,en;q=0.9' });
  let Nok = 0, Nfail = 0;
  for (let i = 0; i < input.length; i++) {
    const tok = input[i] || {};
    try {
      const out = await extractFromPage(page, tok);
      if (out.ok) Nok++; else Nfail++;
      process.stdout.write(JSON.stringify({ idx: i, ...out }) + '\n');
    } catch (err) {
      Nfail++;
      process.stdout.write(JSON.stringify({
        idx: i, ok: false, note: String(err && err.stack || err.message || err).slice(0, 240),
        top10_holding_pct: null, top1_address: '', top1_amount: null, top1_pct: null, top_wallet_value: null,
      }) + '\n');
    }
  }
  await browser.close().catch(() => {});
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch (_) {}
  process.stdout.write(JSON.stringify({ total: input.length, scraped: Nok, failed: Nfail }) + '\n');
}

main().catch(function (e) {
  process.stderr.write('FATAL: ' + (e && e.stack || e) + '\n');
  process.exit(1);
});
