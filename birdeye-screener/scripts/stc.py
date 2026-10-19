#!/usr/bin/env python3
"""Skill #6 Spam Token Cleaner (stc).

================================================================
STEP-BY-STEP WORKFLOW (PURE API, NO BIRDEYE.SO WEB SCRAPING)
================================================================

  STEP 1  /defi/v3/token/list sweep  (50 CU / page)
          - sort_by=market_cap, sort_type=desc
          - server filter: min_market_cap >= $1,000,000,000  (MC threshold)
          - 100 tokens / page, x-chain header per chain
          - chain order: solana -> robinhood -> base -> bsc -> ethereum
          - page stop: hasNext=false  OR  last item MC < $1B  OR  < 100 returned
          - client post-filter: keep only volume_24h_usd <= $50  (dead volume filter)

  STEP 2  Holder concentration top-10 per token  (30 CU / token)
          - SOLANA / ROBINHOOD  ->  /defi/v3/token/holder  (V3)
                address=<token>  mode=wallet  limit=10  offset=0
                returns  data.top10HoldPercent (Solana) / data.top10_hold_percent (RH)
                returns  data.items[] sorted by amount desc
                -> top10_hold_pct native exact (NOT sum-of-10)
                -> top1_address = items[0].owner
                -> top1_amount  = items[0].ui_amount (decimal adjusted)
                -> top1_pct     = top1_amount / totalSupply_from_step1 * 100
                                  OR items[0].amountUsd / (price * supply) proxy
                -> top_wallet_value = top1_pct/100 * market_cap
          - EVM chains (ethereum / base / bsc / arbitrum) -> fallback
                /holder/v1/distribution  (legacy)
                mode=top top_n=10 include_list=true token_address=<token>
                -> same 5 column output, parity schema maintained

  STEP 3  Wallet identity batch label  (~20 CU per 100-address batch)
          - collect DISTINCT top1_addresses
          - filter out addresses that are NOT valid wallet format:
              * Solana  /^[1-9A-HJ-NP-Za-km-z]{32,44}$/
              * EVM     /^0x[a-fA-F0-9]{40}$/
          - POST /identity/v1/multiple  body={addresses:[...100...]}
          - 4 extra columns per token-row:  wallet_type, wallet_label,
                                             wallet_category, wallet_tags

  STEP 4  Sort & output
          Primary sort keys (stable, chained desc then asc):
              1.  market_cap              DESC    (biggest zombie MCs first)
              2.  top_wallet_value        DESC    (whale with most $ bag first)
              3.  liquidity               DESC    (bigger pools first)
              4.  volume_24h_usd          ASC     (driest trading volume first)
          Retained token fields (20 columns) + 5 holder columns + 4 label columns + chain col#1:
              chain
              address, name, symbol, decimals
              liquidity, market_cap, fdv
              recent_listing_time, last_trade_unix_time, holder
              volume_24h_usd, volume_7d_usd, volume_30d_usd
              trade_24h_count, trade_7d_count, trade_30d_count
              global_fees_paid
              price_change_24h_percent, price_change_7d_percent, price_change_30d_percent
              top10_holding_pct, top1_address, top1_amount, top1_pct, top_wallet_value
              wallet_type, wallet_label, wallet_category, wallet_tags

Output formats  (same CLI as birdeye_cli.py for consistency):
  plain           terminal ASCII table (default when invoked manually?)
  telegram        markdown block for paste into bot
  raw-json        single-line json agent pipe
  rendered        UI-hub payload  (DEFAULT, 0-CU format switch later on client)

CU MINIMUM estimate (not billing actual; see cu_breakdown in output):
  50 CU per V3 list page  +  30 CU * tokens (holder V3)  +  20 CU * identity batches.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BIRDEYE_BASE = "https://public-api.birdeye.so"
CHAIN_SHORT = {
    "sol": "solana", "bsc": "bsc", "base": "base",
    "eth": "ethereum", "arc": "arbitrum", "robinhood": "robinhood",
}
# Chain set where /defi/v3/token/holder is supported (documentation: Solana + Robinhood)
HOLDER_V3_NATIVE_CHAINS = {"solana", "robinhood"}
STC_CHAIN_ORDER = ["solana", "robinhood", "base", "bsc", "ethereum"]

HOLDER_SCRAPE_JS = Path(__file__).resolve().parent / "holder_scrape.js"
HOLDER_BROWSER_CHAINS = {"solana", "bsc", "base", "ethereum", "arbitrum", "robinhood"}
HOLDER_SOURCE_DEFAULT = "scrape"  # "scrape" = 0 CU via JS, "api" = Birdeye paid holder APIs (30 CU/token)

TOKEN_BASE_FIELDS = [
    "address", "name", "symbol", "decimals",
    "liquidity", "market_cap", "fdv",
    "recent_listing_time", "last_trade_unix_time", "holder",
    "volume_24h_usd", "volume_7d_usd", "volume_30d_usd",
    "trade_24h_count", "trade_7d_count", "trade_30d_count",
    "global_fees_paid",
    "price_change_24h_percent", "price_change_7d_percent",
    "price_change_30d_percent",
]
HOLDER_COLS = ["top10_holding_pct", "top1_address", "top1_amount",
               "top1_pct", "top_wallet_value"]
LABEL_COLS = ["wallet_type", "wallet_label", "wallet_category", "wallet_tags"]
AUTHORITY_COLS = ["mint_authority", "freeze_authority", "owner_address",
                  "upgrade_authority", "immutable", "metadata_uri",
                  "source_endpoint"]

CACHE_DIR_DEFAULT = Path(os.environ.get("BIRDEYE_CACHE_DIR") or
                         (Path.home() / ".cache" / "birdeye-skills-runs"))
AUTHORITY_CSV_CACHE = CACHE_DIR_DEFAULT / "stc_authority_cache.csv"
AUTHORITY_CACHE_MAX_AGE_DAYS = 30

HOME_ALT_ENV = Path.home() / ".birdeye.env"
LOCAL_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
CONFIG_DIR_ENV = Path.home() / ".config" / "birdeye" / ".env"

SOLANA_ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _load_key() -> str | None:
    if k := os.environ.get("BIRDEYE_API_KEY"):
        return k.strip() or None
    for cand in [HOME_ALT_ENV, LOCAL_ENV_FILE, CONFIG_DIR_ENV]:
        if not cand.exists():
            continue
        for ln in cand.read_text().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if ln.startswith("BIRDEYE_API_KEY="):
                k = ln.split("=", 1)[1].strip().strip('"').strip("'")
                if k:
                    return k
    return None


def _cache_dir() -> Path:
    CACHE_DIR_DEFAULT.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR_DEFAULT


def _safe_run_id(skill: str, ident: str) -> str:
    ident = (ident or "all")[:80]
    ident = "".join(c if c.isalnum() or c in "-_." else "_" for c in ident)
    return f"{skill}_{ident}_{int(time.time())}"


def _delete_cache_prefix(prefix: str) -> int:
    removed = 0
    try:
        for fp in _cache_dir().glob("*.json"):
            try:
                if fp.is_file() and fp.stem.startswith(prefix):
                    fp.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


def _fmt_usd(v, nd=1):
    if v is None or not isinstance(v, (int, float)):
        return "N/A"
    if v == 0:
        return "$0"
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1e9:
        return f"{sign}${av / 1e9:.{nd}f}B"
    if av >= 1e6:
        return f"{sign}${av / 1e6:.{nd}f}M"
    if av >= 1e3:
        return f"{sign}${av / 1e3:.{nd}f}K"
    if av >= 1:
        return f"{sign}${av:.2f}"
    return f"{sign}${av:.4f}"


def _fmt_pct_plain(v):
    if v is None or not isinstance(v, (int, float)):
        return "N/A"
    return f"{v:.2f}%"


def _http_err(status: int, body: str) -> str:
    prefix = {401: "[E401] Unauthorized - bad key.",
              403: "[E403] Forbidden - tier/route blocked.",
              429: "[E429] Rate-limited - slow down.",
              500: "[E500] Birdeye upstream error."}
    return f"{prefix.get(status, f'[E{status}]')} {body[:220]}"


def _be_get(session, key, chain_long, path, params=None):
    t0 = time.perf_counter()
    r = session.get(BIRDEYE_BASE + path,
                    headers={"X-API-KEY": key, "x-chain": chain_long},
                    params=params or {}, timeout=30)
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(_http_err(r.status_code, r.text))
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"json_parse:{e} body:{r.text[:180]}") from None
    es = data.get("success") if isinstance(data, dict) else None
    if isinstance(es, bool) and es is False:
        raise RuntimeError(f"success=false: {json.dumps(data)[:220]}")
    if isinstance(es, (int, float)) and int(es) == 0:
        raise RuntimeError(f"success=0: {json.dumps(data)[:220]}")
    return data, ms


def _be_post(session, key, path, body):
    t0 = time.perf_counter()
    r = session.post(BIRDEYE_BASE + path,
                     headers={"X-API-KEY": key,
                              "Content-Type": "application/json"},
                     json=body, timeout=30)
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        raise RuntimeError(_http_err(r.status_code, r.text))
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"json_parse:{e} body:{r.text[:180]}") from None
    es = data.get("success") if isinstance(data, dict) else None
    if isinstance(es, bool) and es is False:
        raise RuntimeError(f"success=false: {json.dumps(data)[:220]}")
    return data, ms


def _is_wallet_addr(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    return bool(SOLANA_ADDR_RE.match(s) or EVM_ADDR_RE.match(s))


def _to_num(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _empty_holder() -> dict:
    return {"top10_holding_pct": None, "top1_address": "",
            "top1_amount": None, "top1_pct": None,
            "top_wallet_value": None}


def _empty_authority() -> dict:
    return {k: None for k in AUTHORITY_COLS}


# ----------------------------------------------------------- Authority CSV cache
def _auth_cache_header() -> list[str]:
    return ["ts_snapshot_utc", "chain", "address", "symbol", "name"] + AUTHORITY_COLS


def _ensure_authority_csv() -> None:
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not AUTHORITY_CSV_CACHE.exists():
        with AUTHORITY_CSV_CACHE.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(_auth_cache_header())


def _auth_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _auth_row_key(chain: str, address: str) -> str:
    return f"{chain.lower()}:{str(address).strip()}"


def _load_authority_cache() -> dict[str, dict]:
    _ensure_authority_csv()
    out: dict[str, dict] = {}
    cutoff_age_s = AUTHORITY_CACHE_MAX_AGE_DAYS * 24 * 3600
    now_s = int(time.time())
    try:
        with AUTHORITY_CSV_CACHE.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    chain = (r.get("chain") or "").strip()
                    addr = (r.get("address") or "").strip()
                    if not chain or not addr:
                        continue
                    ts_raw = (r.get("ts_snapshot_utc") or "").strip()
                    try:
                        ts_s = int(datetime.fromisoformat(
                            ts_raw.replace("Z", "+00:00")).timestamp())
                    except Exception:
                        ts_s = 0
                    age = now_s - ts_s
                    if age > cutoff_age_s:
                        continue
                    row_out: dict[str, Any] = {"ts_snapshot_utc": ts_raw,
                                               "age_days": round(age / 86400, 2)}
                    for c in AUTHORITY_COLS:
                        row_out[c] = r.get(c) or None
                    row_out["symbol"] = r.get("symbol") or None
                    row_out["name"] = r.get("name") or None
                    out[_auth_row_key(chain, addr)] = row_out
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _append_authority_cache(items: list[dict]) -> int:
    """items: list of dict keys = [chain,address,symbol,name] + AUTHORITY_COLS"""
    if not items:
        return 0
    _ensure_authority_csv()
    ts_now = _auth_now_iso()
    written = 0
    try:
        with AUTHORITY_CSV_CACHE.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for it in items:
                chain = (it.get("chain") or "").strip()
                addr = (it.get("address") or "").strip()
                if not chain or not addr:
                    continue
                row = [ts_now, chain, addr,
                       (it.get("symbol") or "")[:40],
                       (it.get("name") or "")[:80]]
                for c in AUTHORITY_COLS:
                    v = it.get(c)
                    if v is None:
                        row.append("")
                        continue
                    if isinstance(v, bool):
                        row.append("1" if v else "0")
                    else:
                        s = str(v)
                        if len(s) > 2048:
                            s = s[:2048]
                        row.append(s)
                w.writerow(row)
                written += 1
    except Exception as e:
        print(f"[stc auth-cache] append csv fail: {e}",
              file=sys.stderr, flush=True)
        return 0
    return written


def _wipe_authority_csv_rows_for(addresses_chain: list[tuple[str, str]]) -> int:
    """Not a full wipe — rewrite file without matching rows. Called on --nocache."""
    if not AUTHORITY_CSV_CACHE.exists():
        return 0
    kills = {_auth_row_key(c, a) for (c, a) in addresses_chain}
    if not kills:
        # If --nocache with no specific rows, drop whole file
        try:
            AUTHORITY_CSV_CACHE.unlink(missing_ok=True)
            return 1
        except Exception:
            return 0
    kept = []
    removed = 0
    try:
        with AUTHORITY_CSV_CACHE.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = None
            for r in reader:
                if header is None:
                    header = r
                    continue
                if len(r) < 5:
                    continue
                k = _auth_row_key(r[1], r[2])
                if k in kills:
                    removed += 1
                else:
                    kept.append(r)
        if header is None:
            header = _auth_cache_header()
        with AUTHORITY_CSV_CACHE.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(kept)
    except Exception:
        return 0
    return removed


def step_authority_cache(session, key, tokens: list[dict]) -> tuple[dict[int, dict], dict]:
    """Cache-first authority lookup.

    1. Load CSV cache → reuse rows where age <= 30 days (0 CU / each)
    2. Cache misses call /defi/token_security address=<addr> (30 CU / token)
       → freeze/owner/metaplex/mutable fields from proven token-dd endpoint path
       → if mintAuthority present in response extract it; otherwise attempt a
         cheap /defi/token_overview sidecar lookup (21 CU) only when missing.
       → append fresh rows to CSV cache.
    Returns (index->authority_dict, cu_dict).
    """
    cu = {"step4_authority_api_calls": 0,
          "step4_authority_cu": 0,
          "step4_authority_cache_hit": 0,
          "step4_authority_cache_miss": 0}
    if not tokens:
        return {}, cu
    cache = _load_authority_cache()
    out: dict[int, dict] = {}
    misses: list[tuple[int, dict]] = []
    for i, t in enumerate(tokens):
        k = _auth_row_key(str(t.get("_chain") or t.get("chain") or ""),
                          str(t.get("address") or ""))
        if k in cache:
            out[i] = cache[k]
            cu["step4_authority_cache_hit"] += 1
        else:
            misses.append((i, t))
    if not misses:
        return out, cu
    fresh_rows_csv: list[dict] = []
    for i, tok in misses:
        chain_l = (tok.get("_chain") or tok.get("chain") or "solana").strip().lower()
        addr = (tok.get("address") or "").strip()
        if not addr:
            out[i] = _empty_authority()
            continue
        try:
            data, _ = _be_get(session, key, chain_l, "/defi/token_security",
                              params={"address": addr})
            step_cu = 30
            payload = (data.get("data") or {}) if isinstance(data, dict) else {}
            # Canonical keys from verified /defi/token_security payload (PREN1 test):
            #   creatorAddress, ownerAddress, freezeAuthority, freezeable,
            #   metaplexUpdateAuthority, metaplexOwnerUpdateAuthority,
            #   mutableMetadata (bool/None), isToken2022 (bool/None),
            #   ownerOfOwnerAddress (= 111...111 means mint REVOKED for standard SPL),
            #   transferFeeData {transfer_fee_config_authority, fee_editable,...} (Token-2022)
            # ========= Mint authority =========
            mint_a = (payload.get("mintAuthority") or
                      payload.get("mint_authority") or
                      payload.get("mintAuthorityAddress") or None)
            if mint_a is None:
                # Fallback proxy: ownerOfOwnerAddress (when == 111..111 = mint revoked)
                own_own = payload.get("ownerOfOwnerAddress")
                if isinstance(own_own, str) and own_own.strip():
                    mint_a = own_own
            # ========= Freeze authority =========
            fr_a = (payload.get("freezeAuthority") or
                    payload.get("freeze_authority") or
                    payload.get("freezeAuthorityAddress") or None)
            # ========= Owner =========
            own_a = (payload.get("ownerAddress") or
                     payload.get("owner") or
                     payload.get("owner_address") or
                     payload.get("creatorAddress") or None)
            # ========= Upgrade / Metaplex / Token-2022 fee config =========
            up_a = (payload.get("metaplexUpdateAuthority") or
                    payload.get("upgradeAuthority") or
                    payload.get("upgrade_authority") or
                    payload.get("programOwner") or
                    payload.get("metaplexOwnerUpdateAuthority") or None)
            if up_a is None:
                # Token 2022: transfer fee config authority = proxy for upgrade/mutability
                tfd = payload.get("transferFeeData")
                if isinstance(tfd, dict):
                    up_a = (tfd.get("transfer_fee_config_authority") or
                            tfd.get("withdraw_withheld_authority") or None)
            # ========= Immutable / Mutable =========
            imm = None
            mut_md = payload.get("mutableMetadata")
            if isinstance(mut_md, bool):
                imm = not mut_md
            else:
                imm_raw = (payload.get("immutable") or
                           payload.get("isImmutable") or
                           payload.get("tokenImmutable") or
                           payload.get("isMutable"))
                if isinstance(payload.get("isMutable"), bool):
                    imm = not bool(payload["isMutable"])
                elif isinstance(imm_raw, bool):
                    imm = bool(imm_raw)
                elif isinstance(imm_raw, (int, float)):
                    imm = bool(int(imm_raw))
                # Token 2022 fee editability proxy
                if imm is None:
                    tfd2 = payload.get("transferFeeData")
                    if isinstance(tfd2, dict):
                        fe = tfd2.get("fee_editable")
                        if isinstance(fe, bool):
                            imm = not fe
                if imm is None:
                    # freezeable=False → good immutability signal; freezeable True → mutable freeze
                    fz = payload.get("freezeable")
                    if isinstance(fz, bool):
                        imm = None  # don't conflate freezeable w/ overall immutability
            # ========= Metadata URI =========
            md_uri = None
            md = payload.get("metadata")
            if isinstance(md, dict):
                md_uri = (md.get("uri") or md.get("metadataUri") or
                          md.get("metadata_uri") or None)
            md_uri = md_uri or payload.get("metadataUri") or payload.get("uri")
            d = {"mint_authority": mint_a,
                 "freeze_authority": fr_a,
                 "owner_address": own_a,
                 "upgrade_authority": up_a,
                 "immutable": imm,
                 "metadata_uri": md_uri,
                 "source_endpoint": "defi/token_security (30 CU)"}
            out[i] = d
            csv_row = {"chain": tok.get("_chain") or tok.get("chain"),
                       "address": addr,
                       "symbol": tok.get("symbol") or None,
                       "name": tok.get("name") or None,
                       **d}
            fresh_rows_csv.append(csv_row)
            cu["step4_authority_api_calls"] += 1
            cu["step4_authority_cu"] += step_cu
            cu["step4_authority_cache_miss"] += 1
        except Exception as e:
            out[i] = _empty_authority()
            print(f"[stc auth-cache][miss] {chain_l}:{addr[:8]}… err "
                  f"{str(e)[:120]}", file=sys.stderr, flush=True)
    if fresh_rows_csv:
        n_w = _append_authority_cache(fresh_rows_csv)
        print(f"[stc auth-cache] wrote {n_w} fresh rows to "
              f"{AUTHORITY_CSV_CACHE.name}",
              file=sys.stderr, flush=True)
    return out, cu


# ====================================================================== Step 1
def step1_sweep(session, key, min_mc=1_000_000_000.0, max_vol=50.0, chains=None,
                max_tokens_per_chain=200):
    chains = chains or list(STC_CHAIN_ORDER)
    cu = {"step1_token_list_pages": 0, "step1_pages_per_chain": {}}
    out: list[dict] = []
    limit = 100
    for chain_long in chains:
        offset = 0
        page_idx = 0
        chain_cu = 0
        seen: list[dict] = []
        while True:
            if max_tokens_per_chain and len(seen) >= max_tokens_per_chain:
                print(f"[stc step1][{chain_long}] hit max_tokens_per_chain="
                      f"{max_tokens_per_chain}, stopping sweep (CU safe cap)",
                      file=sys.stderr, flush=True)
                break
            if offset + limit > 10000:
                break
            page_limit = limit
            if max_tokens_per_chain:
                page_limit = min(limit, max_tokens_per_chain - len(seen))
                if page_limit <= 0:
                    break
            params = {
                "sort_by": "market_cap", "sort_type": "desc",
                "min_market_cap": min_mc,
                "offset": offset, "limit": page_limit,
            }
            try:
                data, ms = _be_get(session, key, chain_long,
                                   "/defi/v3/token/list", params)
            except Exception as e:
                print(f"[stc step1][{chain_long}] page {page_idx} fail: {e}",
                      file=sys.stderr, flush=True)
                break
            cu["step1_token_list_pages"] += 50
            chain_cu += 50
            payload = data.get("data") or {}
            items = payload.get("items") or []
            print(f"[stc step1][{chain_long}] page={page_idx} "
                  f"items={len(items)} lat={ms}ms total_seen={len(seen) + len(items)}",
                  file=sys.stderr, flush=True)
            if not items:
                break
            for it in items:
                it["_chain"] = chain_long
            seen.extend(items)
            hn = payload.get("hasNext") if "hasNext" in payload else \
                payload.get("has_next", False)
            last = items[-1]
            last_mc = float(last.get("market_cap") or 0)
            if len(items) < page_limit or last_mc < min_mc or hn is False:
                break
            offset += page_limit
            page_idx += 1
        cu["step1_pages_per_chain"][chain_long] = chain_cu
        kept = [it for it in seen
                if float(it.get("volume_24h_usd") or 0) <= max_vol
                and float(it.get("market_cap") or 0) >= min_mc]
        print(f"[stc step1][{chain_long}] collected {len(kept)}/{len(seen)} "
              f"tokens with MC>=${min_mc:,.0f} AND V24h<=${max_vol}",
              file=sys.stderr, flush=True)
        out.extend(kept)
    return out, cu


# ====================================================================== Step 2
def _total_supply_of(tok: dict) -> float | None:
    s = _to_num(tok.get("supply") or tok.get("totalSupply") or
                tok.get("total_supply"))
    if s is not None and s > 0:
        return s
    mc = _to_num(tok.get("market_cap") or 0) or 0
    pr = _to_num(tok.get("price") or tok.get("priceUsd") or 0) or 0
    if mc > 0 and pr > 0:
        return mc / pr
    return None


def _scale_pct_0_100(v: float | None) -> float | None:
    if v is None:
        return None
    if 0.0 <= v <= 1.0:
        return v * 100.0
    return v


def _step2_scrape_js(tokens: list[dict]) -> tuple[dict[int, dict], dict]:
    """Web scrape holder concentration via puppeteer-core Node helper.
       0 Birdeye API CU per token. Returns ({idx: 5cols}, cu_dict)."""
    cu = {"step2_holder_js_calls": 0, "step2_holder_js_ok": 0,
          "step2_holder_js_fail": 0}
    out: dict[int, dict] = {i: _empty_holder() for i, _ in enumerate(tokens)}
    if not HOLDER_SCRAPE_JS.exists():
        print(f"[stc step2][scrape] missing helper: {HOLDER_SCRAPE_JS}",
              file=sys.stderr, flush=True)
        return out, cu
    payload = []
    idx_map: list[int] = []
    for i, tok in enumerate(tokens):
        ch = tok.get("_chain") or ""
        if ch not in HOLDER_BROWSER_CHAINS:
            continue
        addr = tok.get("address") or ""
        if not addr:
            continue
        payload.append({"chain": ch, "address": addr,
                        "market_cap": tok.get("market_cap")})
        idx_map.append(i)
    if not payload:
        return out, cu
    print(f"[stc step2][scrape] calling JS scraper for {len(payload)} "
          f"tokens via puppeteer-core (0 Birdeye holder API CU expected)",
          file=sys.stderr, flush=True)
    try:
        proc = subprocess.run(
            ["node", str(HOLDER_SCRAPE_JS)],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=max(600, 30 * len(payload)), check=False,
        )
        if proc.returncode != 0:
            print(f"[stc step2][scrape] node exit={proc.returncode} "
                  f"err={(proc.stderr or '')[:300]}",
                  file=sys.stderr, flush=True)
            return out, cu
    except Exception as e:
        print(f"[stc step2][scrape] subprocess fail: {e}",
              file=sys.stderr, flush=True)
        return out, cu
    total_line_seen = False
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if "scraped" in rec and "failed" in rec and "total" in rec:
            total_line_seen = True
            print(f"[stc step2][scrape] summary: {json.dumps(rec)}",
                  file=sys.stderr, flush=True)
            continue
        j = int(rec.get("idx", -1))
        if j < 0 or j >= len(idx_map):
            continue
        orig_i = idx_map[j]
        cu["step2_holder_js_calls"] += 1
        if rec.get("ok"):
            cu["step2_holder_js_ok"] += 1
        else:
            cu["step2_holder_js_fail"] += 1
        tok = tokens[orig_i]
        mc = float(tok.get("market_cap") or 0)
        tp = _to_num(rec.get("top1_pct"))
        twv = _to_num(rec.get("top_wallet_value"))
        if twv is None and isinstance(tp, (int, float)) and mc > 0:
            twv = mc * float(tp) / 100.0
        out[orig_i] = {
            "top10_holding_pct": _to_num(rec.get("top10_holding_pct")),
            "top1_address": str(rec.get("top1_address") or ""),
            "top1_amount": _to_num(rec.get("top1_amount")),
            "top1_pct": tp,
            "top_wallet_value": twv,
        }
    if not total_line_seen:
        print(f"[stc step2][scrape] no summary line from JS helper "
              f"(processed {len(payload)} input tokens)",
              file=sys.stderr, flush=True)
    return out, cu


def _step2_birdeye_api(session, key, tokens: list[dict]) -> tuple[dict[int, dict], dict]:
    """Original paid Birdeye holder APIs (fallback when JS scrape unavailable
       or user opts in via --holder-source api). 30 CU per token."""
    cu = {"step2_holder_v3_calls": 0, "step2_holder_legacy_calls": 0,
          "step2_holder_api_calls": 0, "step2_holder_api_ok": 0,
          "step2_holder_api_fail": 0}
    out: dict[int, dict] = {}
    N = len(tokens)
    if N:
        print(f"[stc step2][birdeye-api] starting {N} holder lookups "
              f"(V3-native chains: {sorted(HOLDER_V3_NATIVE_CHAINS)}) "
              f"— ~{N * 30} CU expected",
              file=sys.stderr, flush=True)
    for i, tok in enumerate(tokens):
        chain_long = tok.get("_chain") or "solana"
        addr = tok.get("address")
        mc = float(tok.get("market_cap") or 0)
        supply = _total_supply_of(tok)
        use_v3 = chain_long in HOLDER_V3_NATIVE_CHAINS
        if (i + 1) % 25 == 0 or i == 0 or i == N - 1:
            path = "V3" if use_v3 else "legacy"
            print(f"[stc step2][birdeye-api] {i + 1}/{N} {chain_long} ({path}) "
                  f"addr={(addr or '')[:10]}...",
                  file=sys.stderr, flush=True)
        try:
            if use_v3:
                params = {"address": addr, "mode": "wallet",
                          "limit": 10, "offset": 0}
                data, _ = _be_get(session, key, chain_long,
                                  "/defi/v3/token/holder", params)
                cu["step2_holder_v3_calls"] += 1
            else:
                params = {"token_address": addr, "mode": "top",
                          "top_n": 10, "include_list": "true"}
                data, _ = _be_get(session, key, chain_long,
                                  "/holder/v1/distribution", params)
                cu["step2_holder_legacy_calls"] += 1
            cu["step2_holder_api_calls"] += 1
            cu["step2_holder_api_ok"] += 1
        except Exception as e:
            cu["step2_holder_api_calls"] += 1
            cu["step2_holder_api_fail"] += 1
            print(f"[stc step2][birdeye-api][{chain_long}] holder fail "
                  f"{(addr or '')[:12]}...: {e}", file=sys.stderr, flush=True)
            out[i] = _empty_holder()
            continue
        p = data.get("data") if isinstance(data.get("data"), dict) else {}
        if use_v3:
            raw_top10 = (_to_num(p.get("top10HoldPercent")) or
                         _to_num(p.get("top10_hold_percent")) or
                         _to_num(p.get("top10_pct")) or
                         _to_num(p.get("top_10_pct")))
            top10_pct = _scale_pct_0_100(raw_top10)
            items = p.get("items") or []
            first = items[0] if items else {}
            owner = (first.get("owner") or first.get("address") or
                     first.get("holder") or "")
            amount = (_to_num(first.get("ui_amount")) or
                      _to_num(first.get("amountUsd")) or
                      _to_num(first.get("amount")))
            raw_pct = (_to_num(first.get("percent_of_supply")) or
                       _to_num(first.get("hold_pct")) or
                       _to_num(first.get("pct")))
            if raw_pct is not None:
                pct = _scale_pct_0_100(raw_pct)
            elif amount is not None and supply is not None and supply > 0:
                pct = (amount / supply) * 100.0
            elif amount is not None and top10_pct is not None:
                sum_top10 = 0.0
                for it in items:
                    ia = (_to_num(it.get("ui_amount")) or
                          _to_num(it.get("amount")))
                    if ia is not None:
                        sum_top10 += ia
                if sum_top10 > 0 and top10_pct > 0:
                    pct = (amount / sum_top10) * top10_pct
                else:
                    pct = None
            else:
                pct = None
            twv = mc * (pct / 100.0) if mc and pct is not None else None
            out[i] = {"top10_holding_pct": top10_pct, "top1_address": owner,
                      "top1_amount": amount, "top1_pct": pct,
                      "top_wallet_value": twv}
        else:
            raw_top10 = (_to_num(p.get("top10_pct")) or
                         _to_num(p.get("top_10_pct")) or
                         _to_num(p.get("top10HoldPercent")) or
                         _to_num(p.get("top10_hold_percent")))
            top10_pct = _scale_pct_0_100(raw_top10)
            rows = p.get("rows") or p.get("items") or []
            first = rows[0] if rows else {}
            owner = (first.get("owner") or first.get("address") or
                     first.get("holder") or "")
            amount = (_to_num(first.get("ui_amount")) or
                      _to_num(first.get("amount")))
            raw_pct = (_to_num(first.get("percent_of_supply")) or
                       _to_num(first.get("pct")) or
                       _to_num(first.get("hold_pct")))
            if raw_pct is not None:
                pct = _scale_pct_0_100(raw_pct)
            elif amount is not None and supply is not None and supply > 0:
                pct = (amount / supply) * 100.0
            elif amount is not None and top10_pct is not None:
                sum_top10 = 0.0
                for r in rows:
                    ia = (_to_num(r.get("ui_amount")) or
                          _to_num(r.get("amount")))
                    if ia is not None:
                        sum_top10 += ia
                if sum_top10 > 0 and top10_pct > 0:
                    pct = (amount / sum_top10) * top10_pct
                else:
                    pct = None
            else:
                pct = None
            twv = mc * (pct / 100.0) if mc and pct is not None else 0
            out[i] = {"top10_holding_pct": top10_pct, "top1_address": owner,
                      "top1_amount": amount, "top1_pct": pct,
                      "top_wallet_value": twv}
    return out, cu


def step2_holders(session, key, tokens: list[dict],
                  source: str = HOLDER_SOURCE_DEFAULT):
    """Dispatching step 2: scrape-first (CU saving), fallback API for leftovers.

       source ∈ {scrape, api, scrape+api}
    """
    source = (source or "").strip().lower() or HOLDER_SOURCE_DEFAULT
    cu: dict[str, Any] = {"step2_holder_source": source}
    if source == "api":
        out, sub = _step2_birdeye_api(session, key, tokens)
        cu.update(sub)
        return out, cu
    out_scrape, cu_scrape = _step2_scrape_js(tokens)
    cu.update(cu_scrape)
    if source in {"scrape+api", "hybrid"}:
        miss = [i for i in range(len(tokens))
                if all(v in (None, "") for v in (
                    out_scrape.get(i, {}).get("top10_holding_pct"),
                    out_scrape.get(i, {}).get("top1_address"),
                    out_scrape.get(i, {}).get("top1_amount")))]
        if miss:
            sub_tokens = [tokens[i] for i in miss]
            idx_back = {j: miss[j] for j in range(len(miss))}
            sub_out, sub_cu = _step2_birdeye_api(session, key, sub_tokens)
            for k, v in sub_out.items():
                orig = idx_back.get(k)
                if orig is not None:
                    out_scrape[orig] = v
            for kk, vv in sub_cu.items():
                if isinstance(vv, int):
                    cu[kk] = (cu.get(kk) or 0) + vv
    for i in range(len(tokens)):
        out_scrape.setdefault(i, _empty_holder())
    return out_scrape, cu


# ====================================================================== Step 3
def step3_label(session, key, holders: dict[int, dict]):
    cu = {"step3_batches": 0, "step3_addresses_in": 0, "step3_labels_out": 0}
    addrs: list[str] = []
    for hr in holders.values():
        a = hr.get("top1_address") or ""
        if not _is_wallet_addr(a):
            continue
        if a not in addrs:
            addrs.append(a)
    cu["step3_addresses_in"] = len(addrs)
    labels: dict[str, dict] = {}
    for i in range(0, len(addrs), 100):
        batch = addrs[i:i + 100]
        try:
            data, _ = _be_post(session, key, "/identity/v1/multiple",
                               {"addresses": batch})
            cu["step3_batches"] += 1
        except Exception as e:
            print(f"[stc step3] batch {i // 100} fail: {e}", file=sys.stderr)
            continue
        payload = data.get("data") if isinstance(data, dict) else {}
        if isinstance(payload, dict):
            for a, info in payload.items():
                if not isinstance(info, dict):
                    continue
                labels[a] = {
                    "wallet_type": info.get("type") or "",
                    "wallet_label": info.get("label") or "",
                    "wallet_category": info.get("category") or "",
                    "wallet_tags": info.get("tags") or [],
                }
                cu["step3_labels_out"] += 1
    return labels, cu


# ====================================================================== Step 4
def _sort_key(r: dict):
    mc = float(r.get("market_cap") or 0)
    twv = float(r.get("top_wallet_value") or 0)
    liq = float(r.get("liquidity") or 0)
    v24 = float(r.get("volume_24h_usd") or 0)
    return (-mc, -twv, -liq, v24)


def build_rows(tokens: list[dict], holders: dict[int, dict],
               labels: dict[str, dict],
               authority: dict[int, dict] | None = None) -> list[dict]:
    rows: list[dict] = []
    for i, tok in enumerate(tokens):
        h = holders.get(i) or _empty_holder()
        a = (authority or {}).get(i) or _empty_authority()
        top_addr = h.get("top1_address") or ""
        lab = labels.get(top_addr) or {"wallet_type": "", "wallet_label": "",
                                       "wallet_category": "", "wallet_tags": []}
        row: dict[str, Any] = {"chain": tok.get("_chain") or ""}
        for f in TOKEN_BASE_FIELDS:
            row[f] = tok.get(f)
        for c in HOLDER_COLS:
            row[c] = h.get(c)
        for c in LABEL_COLS:
            row[c] = lab.get(c)
        for c in AUTHORITY_COLS:
            row[c] = a.get(c)
        # Age days for UI cache indicator
        row["authority_age_days"] = a.get("age_days") if isinstance(a, dict) else None
        rows.append(row)
    rows.sort(key=_sort_key)
    return rows


# ============================================================ Output formatters
def _total_cu(cu: dict) -> int:
    step1_pages = int(cu.get("step1_token_list_pages", 0))
    holder_calls = int(cu.get("step2_holder_calls", 0))
    id_batches = int(cu.get("step3_batches", 0))
    auth_cu = int(cu.get("step4_authority_cu", 0))
    return step1_pages + holder_calls * 30 + id_batches * 20 + auth_cu


def _cell(r: dict, col: str) -> str:
    v = r.get(col)
    if col.endswith("_percent") or col.endswith("_pct"):
        return _fmt_pct_plain(v) if isinstance(v, (int, float)) else \
            (str(v) if v is not None else "-")
    if isinstance(v, list):
        return ",".join(str(x) for x in v) if v else "-"
    if v is None:
        return "-"
    return str(v)


def _align(col: str) -> str:
    nums = {"liquidity", "market_cap", "fdv", "volume_24h_usd",
            "volume_7d_usd", "volume_30d_usd", "trade_24h_count",
            "trade_7d_count", "trade_30d_count", "global_fees_paid",
            "price_change_24h_percent", "price_change_7d_percent",
            "price_change_30d_percent", "holder", "decimals",
            "recent_listing_time", "last_trade_unix_time",
            "top10_holding_pct", "top1_amount", "top1_pct",
            "top_wallet_value"}
    return "right" if col in nums else "left"


def _pad(s: str, w: int, align: str) -> str:
    s = str(s)
    if len(s) >= w:
        return s[:w]
    return (" " * (w - len(s)) + s) if align == "right" else \
        (s + " " * (w - len(s)))


def _print_plain(rows, meta):
    cols = ["chain"] + TOKEN_BASE_FIELDS + HOLDER_COLS + LABEL_COLS
    widths = {}
    for i, c in enumerate(cols):
        widths[i] = len(c)
    for r in rows[:150]:
        for i, c in enumerate(cols):
            widths[i] = max(widths[i], min(40, len(_cell(r, c))))
    hdr = " | ".join(_pad(c, widths[i], _align(c))
                     for i, c in enumerate(cols))
    sep = "-+-".join("-" * w for w in widths.values())
    lines = [hdr, sep]
    max_rows = 200
    for r in rows[:max_rows]:
        lines.append(" | ".join(
            _pad(_cell(r, c), widths[i], _align(c))
            for i, c in enumerate(cols)))
    tcu = _total_cu(meta["cu"])
    s1 = meta["cu"].get("step1_token_list_pages", 0)
    s2 = meta["cu"].get("step2_holder_calls", 0)
    s3 = meta["cu"].get("step3_batches", 0)
    lines.append(f"\n[STC] rows={len(rows)} "
                 f"CU list={s1} holders={s2}x30 id={s3}x20 Total~{tcu}")
    print("\n".join(lines))


def _print_telegram(rows, meta):
    head = ["#", "CHAIN", "SYMBOL", "MC", "V24", "TOP10%",
            "TOP1%", "TOP1$", "LABEL", "TYPE"]
    out = ["```"]
    out.append(" | ".join(head))
    for idx, r in enumerate(rows[:60], 1):
        mc = _fmt_usd(r.get("market_cap"), 1)
        v24 = _fmt_usd(r.get("volume_24h_usd"), 2)
        t10 = _fmt_pct_plain(r.get("top10_holding_pct"))
        t1p = _fmt_pct_plain(r.get("top1_pct"))
        twv = _fmt_usd(r.get("top_wallet_value"), 1)
        sym = (r.get("symbol") or "")[:10]
        ch = (r.get("chain") or "")[:8]
        wl = (r.get("wallet_label") or "-")[:16]
        wt = (r.get("wallet_type") or "-")[:10]
        out.append(f"{idx:>2} | {ch:<8} | {sym:<10} | {mc:>9} | "
                   f"{v24:>9} | {t10:>7} | {t1p:>7} | {twv:>9} | "
                   f"{wl:<16} | {wt:<10}")
    tcu = _total_cu(meta["cu"])
    out.append("```")
    out.append(f"Spam Token Cleaner: {len(rows)} tokens found. "
               f"Total CU ~ {tcu}")
    print("\n".join(out))


def _print_rendered(rows, meta):
    def E(s):
        return html.escape("" if s is None else str(s), quote=True)

    cu = meta.get("cu") or {}
    params = meta.get("params") or {}
    tcu = _total_cu(cu)
    n_tok = len(rows)
    chains = params.get("chains") or []
    chain_str = ",".join(chains) if isinstance(chains, list) else str(chains)
    mc_min = _fmt_usd(params.get("min_mc"), 0)
    v_max = _fmt_usd(params.get("max_vol"), 0)
    hit = int(cu.get("step4_authority_cache_hit") or 0)
    miss = int(cu.get("step4_authority_cache_miss") or 0)
    auth_enabled = bool(params.get("authority_enabled"))
    auth_csv_path = str(params.get("authority_csv_cache") or "")
    auth_csv_basename = os.path.basename(auth_csv_path) or "stc_authority_cache.csv"
    holder_src = str(params.get("holder_source") or "")

    # =================================================================== Summary chips
    chips: list[str] = []
    chips.append(f'<span class="stc-chip stc-chip-found" title="Tokens matching filters" '
                 f'style="display:inline-block;margin:2px 4px 2px 0;padding:3px 9px;border-radius:999px;'
                 f'background:#1b2a3f;border:1px solid #2b3f5d;font-size:11px;font-weight:600;'
                 f'color:#9ec8ff;letter-spacing:.2px">🧹 {n_tok} tokens</span>')
    chips.append(f'<span class="stc-chip stc-chip-cu" title="Total Birdeye Compute Units billed" '
                 f'style="display:inline-block;margin:2px 4px;padding:3px 9px;border-radius:999px;'
                 f'background:#3a2a0f;border:1px solid #6b4a1a;font-size:11px;font-weight:600;'
                 f'color:#ffd57e;letter-spacing:.2px">⚡ {tcu} CU</span>')
    chips.append(f'<span class="stc-chip stc-chip-chain" title="Chain scope" '
                 f'style="display:inline-block;margin:2px 4px;padding:3px 9px;border-radius:999px;'
                 f'background:#1e2b1f;border:1px solid #375a3a;font-size:11px;font-weight:600;'
                 f'color:#8be0a0;letter-spacing:.2px">🔗 {E(chain_str)}</span>')
    chips.append(f'<span class="stc-chip stc-chip-mc" title="Minimum market cap filter" '
                 f'style="display:inline-block;margin:2px 4px;padding:3px 9px;border-radius:999px;'
                 f'background:#241d35;border:1px solid #4c3a72;font-size:11px;font-weight:600;'
                 f'color:#cbb5ff;letter-spacing:.2px">MC ≥ {E(mc_min)}</span>')
    chips.append(f'<span class="stc-chip stc-chip-vol" title="Maximum 24h volume filter" '
                 f'style="display:inline-block;margin:2px 4px;padding:3px 9px;border-radius:999px;'
                 f'background:#341a23;border:1px solid #6a2d3f;font-size:11px;font-weight:600;'
                 f'color:#ff9bb0;letter-spacing:.2px">V24h ≤ {E(v_max)}</span>')
    if holder_src:
        chips.append(f'<span class="stc-chip stc-chip-hs" title="Holder data source method" '
                     f'style="display:inline-block;margin:2px 4px;padding:3px 9px;border-radius:999px;'
                     f'background:#0f2a2a;border:1px solid #1d5a5a;font-size:11px;font-weight:600;'
                     f'color:#7ce3e3;letter-spacing:.2px">👜 source: {E(holder_src)}</span>')
    if auth_enabled:
        chip_color = "#2a6d44" if hit > 0 and miss == 0 else ("#6d5a2a" if hit > 0 else "#6d2a2a")
        chip_border = "#3a8c5c" if hit > 0 and miss == 0 else ("#8c7a3a" if hit > 0 else "#8c3a3a")
        chip_text = "#9ef2be" if hit > 0 and miss == 0 else ("#f2d89e" if hit > 0 else "#f29e9e")
        chips.append(f'<span class="stc-chip stc-chip-auth" title="Authority CSV cache · file={E(auth_csv_basename)} · TTL 30 days" '
                     f'style="display:inline-block;margin:2px 4px;padding:3px 9px;border-radius:999px;'
                     f'background:{chip_color};border:1px solid {chip_border};font-size:11px;font-weight:600;'
                     f'color:{chip_text};letter-spacing:.2px">📜 AUTH cache · HIT {hit} / MISS {miss} · {E(auth_csv_basename)}</span>')
    summary_bar = (f'<div class="stc-summary" style="display:flex;flex-wrap:wrap;gap:2px;'
                   f'align-items:center;padding:8px 10px;margin-bottom:10px;border:1px solid #2b3f5d;'
                   f'border-radius:10px;background:linear-gradient(180deg,#0d1728 0%,#0a1220 100%);'
                   f'position:sticky;top:0;z-index:20">{"".join(chips)}</div>')

    # =================================================================== Per-token cards
    card_limit = 200
    cards_html_parts: list[str] = []
    for idx, r in enumerate(rows[:card_limit]):
        chain_raw = r.get("chain") or ""
        chain_slug = str(chain_raw).strip().lower() or "solana"
        addr = r.get("address") or ""
        symbol = (r.get("symbol") or "")[:16] or "???"
        name = (r.get("name") or "")[:48] or "(no name)"
        mc = _fmt_usd(r.get("market_cap"), 1)
        liq = _fmt_usd(r.get("liquidity"), 1)
        v24 = _fmt_usd(r.get("volume_24h_usd"), 2)
        top10_pct_raw = r.get("top10_holding_pct")
        top10_pct = _fmt_pct_plain(top10_pct_raw)
        top1_pct = _fmt_pct_plain(r.get("top1_pct"))
        top1_wv = _fmt_usd(r.get("top_wallet_value"), 1)
        top1_addr = (r.get("top1_address") or "")[:12]
        wallet_label = (r.get("wallet_label") or "").strip()
        wallet_type = (r.get("wallet_type") or "").strip()
        mint_auth = (r.get("mint_authority") or "")[:8]
        freeze_auth_raw = r.get("freeze_authority")
        freeze_txt = "N" if (freeze_auth_raw is None or str(freeze_auth_raw) in ("", "None", "null", "0", "False", "false")) else "Y"
        immutable_raw = r.get("immutable")
        immutable_flag = None
        if isinstance(immutable_raw, bool):
            immutable_flag = immutable_raw
        elif isinstance(immutable_raw, (int, float)):
            immutable_flag = bool(int(immutable_raw))
        elif isinstance(immutable_raw, str):
            s = immutable_raw.strip().lower()
            if s in ("1", "true", "yes", "y", "immutable"):
                immutable_flag = True
            elif s in ("0", "false", "no", "n", "mutable", "", "null", "none"):
                immutable_flag = False
        immutable_ch = "✅" if immutable_flag is True else ("❌" if immutable_flag is False else "—")
        upgrade_auth = (r.get("upgrade_authority") or "")[:8]
        auth_age_raw = r.get("authority_age_days")
        auth_age_str = (
            f"{int(auth_age_raw)}d ago" if isinstance(auth_age_raw, (int, float)) else ("FRESH" if auth_enabled else "SKIPPED")
        )

        # Tier color (Top10 concentration)
        t10_num = float(top10_pct_raw) if isinstance(top10_pct_raw, (int, float)) else -1.0
        if t10_num >= 60:
            tier_label = "🔴 HIGH"
            tier_bg = "#3b1418"
            tier_br = "#a8323c"
            tier_tx = "#ff8d99"
        elif t10_num >= 40:
            tier_label = "🟠 WARN"
            tier_bg = "#3b2a14"
            tier_br = "#a87a32"
            tier_tx = "#ffcc8d"
        elif t10_num >= 0:
            tier_label = "🟢 SAFE"
            tier_bg = "#143b22"
            tier_br = "#32a85c"
            tier_tx = "#8dffb2"
        else:
            tier_label = "⚪ N/A"
            tier_bg = "#23272e"
            tier_br = "#3c4451"
            tier_tx = "#b8c0cc"

        # Action button payloads (JSON → data attrs, CSP safe)
        sel_payload = json.dumps({"chain": chain_slug, "address": addr,
                                  "symbol": symbol, "name": name},
                                 ensure_ascii=False, separators=(",", ":"))
        holders_url = (f"https://birdeye.so/token/{urllib.parse.quote(str(addr))}"
                       f"?chain={urllib.parse.quote(chain_slug)}&tab=holders")

        # Meta pills row
        meta_parts = []
        meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                          f'border-radius:6px;background:#0f1a2e;border:1px solid #1e2f4f;font-size:10.5px;'
                          f'color:#a7c4ee">MC <b style="color:#e6eefc">{E(mc)}</b></span>')
        meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                          f'border-radius:6px;background:#0f1a2e;border:1px solid #1e2f4f;font-size:10.5px;'
                          f'color:#a7c4ee">LIQ <b style="color:#e6eefc">{E(liq)}</b></span>')
        meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                          f'border-radius:6px;background:#240f14;border:1px solid #4f1e25;font-size:10.5px;'
                          f'color:#e6aaae">V24h <b style="color:#ffd5d8">{E(v24)}</b></span>')
        meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                          f'border-radius:6px;background:#1e0f24;border:1px solid #441e4f;font-size:10.5px;'
                          f'color:#cea7ee">T10% <b style="color:#eadcff">{E(top10_pct)}</b></span>')
        meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                          f'border-radius:6px;background:#1e0f24;border:1px solid #441e4f;font-size:10.5px;'
                          f'color:#cea7ee">T1% <b style="color:#eadcff">{E(top1_pct)}</b></span>')
        meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                          f'border-radius:6px;background:#0f2424;border:1px solid #1e4f4f;font-size:10.5px;'
                          f'color:#a7eeee">T1$ <b style="color:#dcfcfc">{E(top1_wv)}</b></span>')
        if top1_addr:
            meta_parts.append(f'<span class="stc-mp" style="display:inline-block;margin:2px 3px;padding:2px 7px;'
                              f'border-radius:6px;background:#1a1a0f;border:1px solid #45451f;font-size:10.5px;'
                              f'color:#d9d9a4">whale <b style="color:#f2f2cc;font-family:monospace">{E(top1_addr)}…</b></span>')

        # Wallet label pill (if any)
        wallet_pill = ""
        if wallet_label:
            wtype_txt = f" · type:{E(wallet_type)}" if wallet_type else ""
            wallet_pill = (f'<div style="margin-top:4px">'
                           f'<span class="stc-wallet-pill" style="display:inline-block;padding:2px 8px;'
                           f'border-radius:999px;background:#22334d;border:1px solid #45668f;font-size:10.5px;'
                           f'color:#c9dcf4;font-weight:600">👤 {E(wallet_label)}{E(wtype_txt)}</span></div>')

        # Authority bottom strip
        auth_items = [
            f'🔐 Mint:{E(mint_auth) + ("…" if mint_auth else "—")}',
            f'Freeze:{E(freeze_txt)}',
            f'Immutable:{immutable_ch}',
        ]
        if upgrade_auth:
            auth_items.append(f'Upgrade:{E(upgrade_auth)}…')
        auth_items.append(f'💾 {E(auth_age_str)}')
        auth_strip = (f'<div style="margin-top:7px;padding:4px 8px;border-top:1px dashed #2b3f5d;'
                      f'font-size:10.5px;color:#8fa3c2;letter-spacing:.1px;line-height:1.55">'
                      + " | ".join(auth_items) + "</div>")

        # Header
        chain_badge = (f'<span style="display:inline-block;margin-right:5px;padding:1px 7px;border-radius:5px;'
                       f'background:#132038;border:1px solid #2b436d;font-size:10px;color:#90b0dc;'
                       f'font-weight:700;text-transform:uppercase;letter-spacing:.5px">{E(chain_slug)}</span>')
        tier_badge = (f'<span style="display:inline-block;margin-left:6px;padding:2px 8px;border-radius:999px;'
                      f'background:{tier_bg};border:1px solid {tier_br};font-size:10px;font-weight:800;'
                      f'color:{tier_tx};letter-spacing:.4px">{tier_label} T10</span>')

        header_html = (
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;'
            f'gap:4px;margin-bottom:6px">'
            f'  <div style="display:flex;align-items:center;flex-wrap:wrap;min-width:0">'
            f'    <span style="font-weight:800;font-size:13.5px;color:#f3f6fc;letter-spacing:.15px;'
            f'    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:320px">'
            f'      {E(symbol)}'
            f'      <span style="font-weight:500;color:#9cb4d8;margin-left:6px;font-size:11.5px">'
            f'        — {E(name)}'
            f'      </span>'
            f'    </span>'
            f'    {chain_badge}'
            f'    {tier_badge}'
            f'  </div>'
            f'  <span style="font-family:monospace;font-size:10px;color:#6f86a7">'
            f'    #{idx + 1}'
            f'  </span>'
            f'</div>'
        )

        # Action buttons (RIGHT side = 3 big stacked)
        btn_style_base = (
            "display:block;width:100%;margin:3px 0;padding:7px 9px;border-radius:8px;"
            "border:1px solid;font-size:11px;font-weight:700;cursor:pointer;"
            "transition:transform .05s ease, filter .15s ease;letter-spacing:.25px;"
            "white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
        )
        btn_dd = (f'<button class="stc-btn stc-btn-dd" data-stc-action="dd" '
                  f'data-stc-sel="{E(sel_payload)}" data-stc-side="token_dd" '
                  f'data-stc-skill="dd" '
                  f'style="{btn_style_base}background:#0f2842;border-color:#2a5a92;color:#aad3ff;'
                  f'text-align:left">'
                  f'🛡 Token DD <span style="font-weight:500;color:#6fa6e2">(~71 CU)</span></button>')
        btn_rc = (f'<button class="stc-btn stc-btn-rc" data-stc-action="rugcheck" '
                  f'data-stc-sel="{E(sel_payload)}" data-stc-side="rugcheck_risk_audit" '
                  f'data-stc-skill="rugcheck_risk_audit" '
                  f'style="{btn_style_base}background:#3a2208;border-color:#8a5a1c;color:#ffd199;'
                  f'text-align:left">'
                  f'🔍 RugCheck Audit <span style="font-weight:500;color:#d99e5a">(~142-172 CU)</span></button>')
        btn_br = (f'<button class="stc-btn stc-btn-br" data-stc-action="birdeye" '
                  f'data-birdeye-url="{E(holders_url)}" '
                  f'style="{btn_style_base}background:#22163a;border-color:#5a3a92;color:#cbb5ff;'
                  f'text-align:left">'
                  f'🌐 Open Birdeye Holders <span style="font-weight:500;color:#9678e0">(0 CU)</span></button>')

        card_html = (
            f'<div class="stc-card" style="padding:10px 12px;margin:7px 0;border:1px solid #263a5e;'
            f'border-radius:11px;background:linear-gradient(180deg,#0f1a30 0%,#0b1326 100%)">'
            + header_html
            + f'<div style="display:flex;gap:10px;align-items:stretch">'
            + f'  <div style="flex:1 1 auto;min-width:0">'
            + f'    <div style="margin-top:2px">{"".join(meta_parts)}</div>'
            + wallet_pill
            + auth_strip
            + f'  </div>'
            + f'  <div style="flex:0 0 208px;min-width:208px;max-width:208px;display:flex;'
            f'       flex-direction:column;justify-content:center;padding-left:6px;'
            f'       border-left:1px dashed #2b3f5d">'
            + btn_dd + btn_rc + btn_br
            + f'  </div>'
            + f'</div>'
            + f'</div>'
        )
        cards_html_parts.append(card_html)

    trunc_note = ""
    if len(rows) > card_limit:
        trunc_note = (f'<div style="margin-top:8px;padding:6px 10px;border:1px dashed #7a5a1e;'
                      f'border-radius:8px;background:#2a1f05;color:#e8c06a;font-size:11px">'
                      f'⚠ Render cap: showing first {card_limit} of {len(rows)} total cards. '
                      f'Use --max-tokens / --min-mc / --max-vol filters to reduce scope, '
                      f'or inspect CLI stdout below for all rows.</div>')

    # =================================================================== CSP-safe inline event listener (vanilla JS)
    script_stc = r"""<script>
(function(){
  try{
    var scope=document.currentScript&&document.currentScript.parentElement?document.currentScript.parentElement:document;
    function runSide(side,sel,skill){
      try{
        if(window.setSelection && sel) try{window.setSelection(sel);}catch(_){}
        if(window.STATE){
          try{ if(sel) window.STATE.selection=sel; }catch(_){}
          try{ if(skill) window.STATE.skill=skill; }catch(_){}
        }
        try{ if(window.drillMode && skill && skill.indexOf('dd')>=0) window.drillMode('token-dd'); }catch(_){}
        try{ if(window.renderSkillCtrl) window.renderSkillCtrl(); }catch(_){}
        try{ if(window.runCLI && side) window.runCLI(side); }catch(_){}
      }catch(e){ console.warn('[STC action] hub hook failed:', e);
        alert('Skill hook not ready. Side='+side+' | Addr='+(sel&&sel.address));
      }
    }
    scope.querySelectorAll('button[data-stc-action]').forEach(function(b){
      b.addEventListener('click', function(ev){
        ev.preventDefault(); ev.stopPropagation();
        var act=b.getAttribute('data-stc-action')||'';
        var sel=null; try{ var sp=b.getAttribute('data-stc-sel')||''; if(sp) sel=JSON.parse(sp); }catch(_){}
        var side=b.getAttribute('data-stc-side')||'';
        var skill=b.getAttribute('data-stc-skill')||(act==='rugcheck'?'rugcheck_risk_audit':'dd');
        if(act==='birdeye'){
          var url=b.getAttribute('data-birdeye-url')||'';
          if(url) window.open(url,'_blank','noopener,noreferrer');
          return;
        }
        b.style.filter='brightness(1.4)';
        setTimeout(function(){ b.style.filter=''; },120);
        runSide(side,sel,skill);
      }, false);
    });
    scope.querySelectorAll('button[data-stc-action]').forEach(function(b){
      b.addEventListener('mousedown', function(){ b.style.transform='translateY(1px)'; });
      b.addEventListener('mouseup',   function(){ b.style.transform=''; });
      b.addEventListener('mouseleave',function(){ b.style.transform=''; });
    });
  }catch(e){ console.warn('[STC render init]', e); }
})();
</script>"""

    # =================================================================== Wrap
    inner = (
        summary_bar
        + (trunc_note if trunc_note else "")
        + f'<div class="stc-cards-wrap" style="margin:0">'
        + ("".join(cards_html_parts) if cards_html_parts else
           (f'<div style="padding:22px;text-align:center;color:#98a9c6;font-size:12px;'
            f'border:1px dashed #3c4d6c;border-radius:10px">'
            f'🧹 No tokens matched the filter. Try lowering --min-mc or raising --max-vol.</div>'))
        + f'</div>'
        + script_stc
    )
    html_wrap = (
        f'<div class="render-stc" style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,'
        f'Roboto,Helvetica,Arial,sans-serif;color:#e6edf8;background:transparent">'
        + inner
        + f'</div>'
    )

    summary_obj = {
        "total_tokens": n_tok,
        "cu_total": tcu,
        "chains": chains,
        "min_mc": params.get("min_mc"),
        "max_vol": params.get("max_vol"),
        "holder_source": holder_src,
        "authority_cache": {
            "enabled": auth_enabled,
            "hit": hit,
            "miss": miss,
            "csv_file": auth_csv_path,
            "ttl_days": AUTHORITY_CACHE_MAX_AGE_DAYS,
        },
        "max_tokens_per_chain": params.get("max_tokens_per_chain"),
        "max_tokens_global": params.get("max_tokens_global"),
        "elapsed_ms": params.get("elapsed_ms"),
        "rendered_cards": min(len(rows), card_limit),
    }

    payload = {
        "schemaVersion": 1,
        "kind": "spam-token-cleaner",
        "params": meta["params"],
        "columns": ["chain"] + TOKEN_BASE_FIELDS + HOLDER_COLS + LABEL_COLS + AUTHORITY_COLS + ["authority_age_days"],
        "rows": rows,
        "summary": summary_obj,
        "html": html_wrap,
        "total_tokens": len(rows),
        "snapshot_time": int(time.time()),
        "cu_used_total": tcu,
        "cu_breakdown": meta["cu"],
        "format_renderers": ["render", "plain", "telegram", "raw-json"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_raw_json(rows, meta, run_id):
    envelope = {
        "runId": run_id,
        "cached": False,
        "cu_used_total": _total_cu(meta["cu"]),
        "cu_breakdown": meta["cu"],
        "params": meta["params"],
        "columns": ["chain"] + TOKEN_BASE_FIELDS + HOLDER_COLS + LABEL_COLS,
        "rows": rows,
        "total_tokens": len(rows),
        "snapshot_time": int(time.time()),
    }
    print(json.dumps(envelope, ensure_ascii=False))


# ============================================================ Main entry point
def main():
    p = argparse.ArgumentParser(
        prog="stc",
        description="Spam Token Cleaner - high-MC low-volume top-holder sweep")
    p.add_argument("--min-mc", type=float, default=1_000_000_000.0,
                   help="Minimum market_cap USD (default 1e9 = $1B)")
    p.add_argument("--max-vol", type=float, default=50.0,
                   help="Maximum volume_24h_usd USD (default $50)")
    p.add_argument("--chains", type=str,
                   default=",".join(STC_CHAIN_ORDER),
                   help="Comma chain list. Default order: "
                        "solana,robinhood,base,bsc,ethereum")
    p.add_argument("--max-tokens-per-chain", type=int, default=200,
                   help="Cap how many tokens to scan per chain (CU safe)."
                        " Default 200 (user extended limit). Use 0 for unlimited.")
    p.add_argument("--max-tokens", type=int, default=None,
                   help="Global cap across all chains (applied after sweep)."
                        " Default None = unlimited.")
    p.add_argument("--holder-source",
                   choices=["scrape", "api", "scrape+api"],
                   default=HOLDER_SOURCE_DEFAULT,
                   help="How to acquire holder top1/top10: "
                        "scrape = birdeye.so holders tab via puppeteer-core "
                        "JS (0 holder API CU, default). "
                        "api = Birdeye /defi/v3/token/holder (30 CU/token). "
                        "scrape+api = scrape-first, fill empty via API fallback.")
    p.add_argument("--format",
                   choices=["plain", "telegram", "raw-json", "rendered"],
                   default="rendered",
                   help="Output format (default rendered for UI hub)")
    p.add_argument("--nocache", "--no-cache", "--force-fetch",
                   "--force-fresh", dest="nocache", action="store_true",
                   help="Wipe prior stc_ cache prefix AND drop authority cache CSV rows for tokens in this run (force fresh)")
    p.add_argument("--skip-authority", dest="skip_authority", action="store_true",
                   help="Skip Step 4 authority metadata fetch (CSV cache + /defi/token_security/v2 30 CU/tok miss). "
                        "Default = fetch + cache authority (CSV 30-day TTL).")
    p.add_argument("--run-id", type=str, default=None,
                   help="Optional explicit run id for cache key")
    p.add_argument("--api-key", type=str, default=None,
                   help="Override Birdeye API key (else env/file)")
    args = p.parse_args()

    key = args.api_key or _load_key()
    if not key:
        print("[stc] missing BIRDEYE_API_KEY. Set via --api-key, "
              "BIRDEYE_API_KEY env, or ~/.birdeye.env",
              file=sys.stderr)
        sys.exit(2)

    chains_raw = [c.strip() for c in args.chains.split(",") if c.strip()]
    chains = [CHAIN_SHORT.get(c, c) for c in chains_raw]

    ident = f"mc{int(args.min_mc // 1e6)}M_v{int(args.max_vol)}"
    run_id = args.run_id or _safe_run_id("stc", ident)
    if args.nocache:
        _delete_cache_prefix("stc_")
        # Also drop authority CSV rows for tokens we are about to re-scan
        # (do it lazily: drop whole file for simplicity since step1 result unknown yet)
        _wipe_authority_csv_rows_for([])

    session = requests.Session()
    t0 = time.time()

    mt_per_chain = args.max_tokens_per_chain
    if isinstance(mt_per_chain, int) and mt_per_chain <= 0:
        mt_per_chain = None  # 0 → unlimited (user opted out of safe default cap)
    tokens, cu1 = step1_sweep(session, key, args.min_mc, args.max_vol, chains,
                              max_tokens_per_chain=mt_per_chain)
    if isinstance(args.max_tokens, int) and args.max_tokens > 0:
        tokens = tokens[:args.max_tokens]
        print(f"[stc] applied global --max-tokens cap → {len(tokens)} tokens",
              file=sys.stderr, flush=True)
    holders, cu2 = step2_holders(session, key, tokens,
                                 source=args.holder_source)
    labels, cu3 = step3_label(session, key, holders)
    authority, cu4 = ({}, {}) if args.skip_authority else \
        step_authority_cache(session, key, tokens)
    rows = build_rows(tokens, holders, labels, authority=authority)
    elapsed = int((time.time() - t0) * 1000)

    meta = {
        "cu": {**cu1, **cu2, **cu3, **cu4},
        "params": {
            "min_mc": args.min_mc,
            "max_vol": args.max_vol,
            "chains": chains,
            "elapsed_ms": elapsed,
            "run_id": run_id,
            "holder_source": args.holder_source,
            "authority_enabled": not bool(args.skip_authority),
            "authority_csv_cache": str(AUTHORITY_CSV_CACHE),
            "max_tokens_per_chain": (args.max_tokens_per_chain or 0),
            "max_tokens_global": (args.max_tokens if isinstance(args.max_tokens, int) and args.max_tokens > 0 else len(tokens)),
        },
    }
    fmt = args.format
    if fmt == "plain":
        _print_plain(rows, meta)
    elif fmt == "telegram":
        _print_telegram(rows, meta)
    elif fmt == "raw-json":
        _print_raw_json(rows, meta, run_id)
    else:
        _print_rendered(rows, meta)


if __name__ == "__main__":
    main()
