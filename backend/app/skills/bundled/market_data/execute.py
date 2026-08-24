"""Market data from Eastmoney's public quote endpoints.

Chosen over Yahoo/Google Finance because those are not reachable from mainland
China, while Eastmoney covers A-shares, Hong Kong, US listings, FX and
commodities from one schema and needs no key.

Field codes (with fltt=2 the numeric fields arrive already scaled):
  f2 last   f3 chg%   f4 chg    f5 volume(手)  f6 turnover(元)  f7 amplitude%
  f8 turnover-rate%   f9 PE(TTM)   f12 code   f13 market   f14 name
  f15 high  f16 low   f17 open  f18 prev close   f20 mktcap  f21 float cap
  f23 PB    f62 main net inflow   f184 main net inflow share%
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

_TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_PUSH = "https://push2.eastmoney.com/api/qt"
_PUSH_HIS = "https://push2his.eastmoney.com/api/qt"
_SUGGEST = "https://searchapi.eastmoney.com/api/suggest/get"

_QUOTE_FIELDS = (
    "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f62,f184"
)

# A-share boards: 沪A 深A 创业板 科创板 北交所
_A_SHARE_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"

_OVERVIEW: list[tuple[str, str]] = [
    ("1.000001", "上证指数"),
    ("0.399001", "深证成指"),
    ("0.399006", "创业板指"),
    ("1.000688", "科创50"),
    ("1.000300", "沪深300"),
    ("1.000905", "中证500"),
    ("0.899050", "北证50"),
    ("100.HSI", "恒生指数"),
    ("124.HSTECH", "恒生科技"),
    ("100.DJIA", "道琼斯"),
    ("100.NDX", "纳斯达克100"),
    ("100.SPX", "标普500"),
    ("100.N225", "日经225"),
    ("133.USDCNH", "离岸人民币 USD/CNH"),
    ("101.GC00Y", "COMEX黄金主连"),
    ("102.CL00Y", "NYMEX原油(WTI)"),
    ("112.B00Y", "布伦特原油当月连续"),
]

_INDEX_ALIASES = {
    "上证指数": "1.000001", "上证": "1.000001", "sh000001": "1.000001",
    "深证成指": "0.399001", "sz399001": "0.399001",
    "创业板指": "0.399006", "sz399006": "0.399006",
    "科创50": "1.000688", "沪深300": "1.000300", "中证500": "1.000905",
    "北证50": "0.899050", "恒生指数": "100.HSI", "hsi": "100.HSI",
    "恒生科技": "124.HSTECH", "道指": "100.DJIA", "纳指": "100.NDX",
    "纳斯达克": "100.NDX", "标普500": "100.SPX", "spx": "100.SPX",
}

_CODE_SUFFIX = re.compile(r"^(?P<code>[0-9A-Za-z]+)[.\-](?P<mkt>SH|SS|SZ|BJ|HK|US)$", re.I)
_PREFIXED = re.compile(r"^(?P<mkt>sh|sz|bj|hk)(?P<code>[0-9]{5,6})$", re.I)


async def execute(
    mode: str = "overview",
    symbols: list[str] | None = None,
    days: int = 60,
    board: str = "industry",
    rank_by: str = "change",
    count: int = 15,
) -> str:
    mode = (mode or "overview").strip().lower()
    syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"},
    ) as client:
        try:
            if mode == "overview":
                return await _overview(client)
            if mode == "quote":
                if not syms:
                    return "Error: mode=quote requires at least one entry in `symbols`."
                return await _quote(client, syms)
            if mode == "history":
                if not syms:
                    return "Error: mode=history requires a symbol in `symbols`."
                return await _history(client, syms[0], max(5, min(int(days or 60), 250)))
            if mode == "movers":
                return await _movers(client, rank_by, max(5, min(int(count or 15), 50)))
            if mode == "sectors":
                return await _sectors(client, board, rank_by, max(5, min(int(count or 15), 50)))
        except httpx.HTTPError as exc:
            return f"Error: market data request failed ({type(exc).__name__}: {exc}). No numbers returned - do not estimate."
    return f"Error: unknown mode {mode!r}. Use overview | quote | history | movers | sectors."


# -- modes -------------------------------------------------------------------

async def _overview(client: httpx.AsyncClient) -> str:
    rows = await _ulist(client, [secid for secid, _ in _OVERVIEW])
    by_id = {r["secid"]: r for r in rows}
    lines = [
        "# Cross-market snapshot",
        "",
        f"Fetched {_now()} UTC from Eastmoney. Values are last traded prices; "
        "outside session hours they are the most recent close.",
        "",
        "| Market | Last | Chg % | Chg | High | Low | Prev close |",
        "|---|---|---|---|---|---|---|",
    ]
    missing = []
    for secid, label in _OVERVIEW:
        row = by_id.get(secid)
        if not row:
            missing.append(label)
            continue
        lines.append(
            f"| {label} | {_num(row.get('f2'))} | {_pct(row.get('f3'))} | "
            f"{_num(row.get('f4'))} | {_num(row.get('f15'))} | {_num(row.get('f16'))} | "
            f"{_num(row.get('f18'))} |"
        )
    if missing:
        lines.append("")
        lines.append(f"Not returned by the endpoint: {', '.join(missing)}.")
    return "\n".join(lines)


async def _quote(client: httpx.AsyncClient, symbols: list[str]) -> str:
    resolved = await asyncio.gather(*[_resolve(client, s) for s in symbols])
    pairs = [(sym, secid) for sym, secid in zip(symbols, resolved)]
    good = [secid for _, secid in pairs if secid]

    rows = await _ulist(client, good) if good else []
    by_id = {r["secid"]: r for r in rows}

    # A code can parse cleanly yet still address the wrong market (fund and
    # bond prefixes differ from equity ones). Rather than report an empty row,
    # ask Eastmoney's own search to resolve it and retry once.
    retry = [(i, sym) for i, (sym, secid) in enumerate(pairs) if not secid or secid not in by_id]
    if retry:
        found = await asyncio.gather(*[_suggest(client, sym) for _, sym in retry])
        second = [secid for secid in found if secid]
        if second:
            for row in await _ulist(client, second):
                by_id[row["secid"]] = row
            for (index, _), secid in zip(retry, found):
                if secid and secid in by_id:
                    pairs[index] = (pairs[index][0], secid)

    unresolved = [sym for sym, secid in pairs if not secid or secid not in by_id]

    lines = [
        "# Quotes",
        "",
        f"Fetched {_now()} UTC from Eastmoney.",
        "",
        "| Symbol | Name | Last | Chg % | Open | High | Low | Prev | Volume(手) | "
        "Turnover(亿) | Turn% | PE(TTM) | PB | Mkt cap(亿) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sym, secid in pairs:
        row = by_id.get(secid or "")
        if not row:
            continue
        lines.append(
            f"| {sym} | {row.get('f14', '?')} | {_num(row.get('f2'))} | {_pct(row.get('f3'))} | "
            f"{_num(row.get('f17'))} | {_num(row.get('f15'))} | {_num(row.get('f16'))} | "
            f"{_num(row.get('f18'))} | {_num(row.get('f5'))} | {_yi(row.get('f6'))} | "
            f"{_num(row.get('f8'))} | {_num(row.get('f9'))} | {_num(row.get('f23'))} | "
            f"{_yi(row.get('f20'))} |"
        )
    if unresolved:
        lines.append("")
        lines.append(
            "**Unresolved symbols (no quote returned - do not invent one): "
            + ", ".join(unresolved)
            + "**"
        )
    return "\n".join(lines)


async def _history(client: httpx.AsyncClient, symbol: str, days: int) -> str:
    secid = await _resolve(client, symbol)
    if not secid:
        return f"Error: could not resolve symbol {symbol!r} to an Eastmoney secid."
    resp = await client.get(
        f"{_PUSH_HIS}/stock/kline/get",
        params={
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101,
            "fqt": 1,
            "end": "20500101",
            "lmt": days,
        },
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        return f"Error: no daily bars returned for {symbol} (secid {secid})."

    bars = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 9:
            continue
        bars.append(
            {
                "date": parts[0],
                "open": _f(parts[1]),
                "close": _f(parts[2]),
                "high": _f(parts[3]),
                "low": _f(parts[4]),
                "volume": _f(parts[5]),
                "amount": _f(parts[6]),
                "pct": _f(parts[8]),
            }
        )

    closes = [b["close"] for b in bars if b["close"] is not None]
    highs = [b["high"] for b in bars if b["high"] is not None]
    lows = [b["low"] for b in bars if b["low"] is not None]
    last = closes[-1] if closes else None
    window_high = max(highs) if highs else None
    window_low = min(lows) if lows else None

    lines = [
        f"# Daily history - {data.get('name', symbol)} ({data.get('code', '')}) [secid {secid}]",
        "",
        f"{len(bars)} 前复权 daily bars, fetched {_now()} UTC from Eastmoney.",
        "",
        "## Derived statistics",
        f"- Last close: {_num(last)}",
        f"- MA5 / MA20 / MA60: {_num(_ma(closes, 5))} / {_num(_ma(closes, 20))} / {_num(_ma(closes, 60))}",
        f"- Window high / low: {_num(window_high)} / {_num(window_low)}",
        f"- Distance from window high: {_pct(_change(last, window_high))}",
        f"- Return over window: {_pct(_change(last, closes[0]) if closes else None)}",
        "",
        "## Recent bars (most recent last)",
        "| Date | Open | High | Low | Close | Chg % | Amount(亿) |",
        "|---|---|---|---|---|---|---|",
    ]
    for bar in bars[-30:]:
        lines.append(
            f"| {bar['date']} | {_num(bar['open'])} | {_num(bar['high'])} | "
            f"{_num(bar['low'])} | {_num(bar['close'])} | {_pct(bar['pct'])} | "
            f"{_yi(bar['amount'])} |"
        )
    return "\n".join(lines)


async def _movers(client: httpx.AsyncClient, rank_by: str, count: int) -> str:
    fid = "f62" if rank_by == "main_inflow" else "f3"
    gainers, losers = await asyncio.gather(
        _clist(client, _A_SHARE_FS, fid, count, descending=True),
        _clist(client, _A_SHARE_FS, fid, count, descending=False),
    )
    label = "主力净流入" if rank_by == "main_inflow" else "涨跌幅"
    lines = [
        f"# A-share movers (ranked by {label})",
        "",
        f"Fetched {_now()} UTC from Eastmoney. Universe: 沪A/深A/创业板/科创板/北交所.",
        "",
        f"## Top {len(gainers)} by {label} (descending)",
    ]
    lines.extend(_rank_table(gainers))
    lines.append("")
    lines.append(f"## Bottom {len(losers)} by {label} (ascending)")
    lines.extend(_rank_table(losers))
    return "\n".join(lines)


async def _sectors(client: httpx.AsyncClient, board: str, rank_by: str, count: int) -> str:
    fs = "m:90+t:3+f:!50" if board == "concept" else "m:90+t:2+f:!50"
    fid = "f62" if rank_by == "main_inflow" else "f3"
    top, bottom = await asyncio.gather(
        _clist(client, fs, fid, count, descending=True),
        _clist(client, fs, fid, count, descending=False),
    )
    board_label = "概念板块" if board == "concept" else "行业板块"
    label = "主力净流入" if rank_by == "main_inflow" else "涨跌幅"
    lines = [
        f"# {board_label} ranking (by {label})",
        "",
        f"Fetched {_now()} UTC from Eastmoney.",
        "",
        f"## Strongest {len(top)}",
    ]
    lines.extend(_rank_table(top))
    lines.append("")
    lines.append(f"## Weakest {len(bottom)}")
    lines.extend(_rank_table(bottom))
    return "\n".join(lines)


# -- endpoint wrappers -------------------------------------------------------

async def _ulist(client: httpx.AsyncClient, secids: list[str]) -> list[dict]:
    """Batch quote lookup. Chunked because the endpoint rejects very long lists."""
    chunks = [secids[i : i + 40] for i in range(0, len(secids), 40)]
    results = await asyncio.gather(
        *[
            client.get(
                f"{_PUSH}/ulist.np/get",
                params={
                    "secids": ",".join(chunk),
                    "fields": _QUOTE_FIELDS,
                    "fltt": 2,
                    "invt": 2,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                },
            )
            for chunk in chunks
        ],
        return_exceptions=True,
    )
    rows: list[dict] = []
    for chunk, resp in zip(chunks, results):
        if isinstance(resp, Exception):
            continue
        try:
            payload = (resp.json() or {}).get("data") or {}
        except json.JSONDecodeError:
            continue
        for item in payload.get("diff") or []:
            market = item.get("f13")
            code = item.get("f12")
            if market is None or code is None:
                continue
            item["secid"] = f"{market}.{code}"
            rows.append(item)
    # Preserve caller order where possible.
    order = {s: i for i, s in enumerate(secids)}
    rows.sort(key=lambda r: order.get(r["secid"], 10_000))
    return rows


async def _clist(
    client: httpx.AsyncClient, fs: str, fid: str, count: int, descending: bool
) -> list[dict]:
    resp = await client.get(
        f"{_PUSH}/clist/get",
        params={
            "pn": 1,
            "pz": count,
            "po": 1 if descending else 0,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": fid,
            "fs": fs,
            "fields": "f2,f3,f5,f6,f8,f9,f12,f13,f14,f20,f62,f184",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        },
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    return list(data.get("diff") or [])


async def _resolve(client: httpx.AsyncClient, symbol: str) -> str | None:
    """Map a user-facing symbol to an Eastmoney `market.code` secid."""
    raw = symbol.strip()
    lowered = raw.lower()
    if lowered in _INDEX_ALIASES:
        return _INDEX_ALIASES[lowered]
    if raw in _INDEX_ALIASES:
        return _INDEX_ALIASES[raw]
    if re.fullmatch(r"\d{1,3}\.\w+", raw):  # already a secid
        return raw

    match = _CODE_SUFFIX.match(raw)
    if match:
        code, mkt = match.group("code"), match.group("mkt").upper()
        if mkt in ("SH", "SS"):
            return f"1.{code}"
        if mkt in ("SZ", "BJ"):
            return f"0.{code}"
        if mkt == "HK":
            return f"116.{code.zfill(5)}"
        if mkt == "US":
            return await _suggest(client, code)

    match = _PREFIXED.match(raw)
    if match:
        code, mkt = match.group("code"), match.group("mkt").lower()
        if mkt == "sh":
            return f"1.{code}"
        if mkt in ("sz", "bj"):
            return f"0.{code}"
        if mkt == "hk":
            return f"116.{code.zfill(5)}"

    if re.fullmatch(r"\d{6}", raw):
        return f"{_a_share_market(raw)}.{raw}"
    if re.fullmatch(r"\d{4,5}", raw):
        return f"116.{raw.zfill(5)}"

    return await _suggest(client, raw)


def _a_share_market(code: str) -> int:
    """Eastmoney market number for a 6-digit 沪深北 code.

    1 = 上交所, 0 = 深交所/北交所. Funds and bonds do not follow the equity
    prefixes: 51xxxx/56xxxx/58xxxx are Shanghai ETFs while 15xxxx/16xxxx are
    Shenzhen ones, so a naive "starts with 6" rule silently mis-routes them and
    the quote comes back empty.
    """
    if code.startswith(("11", "13")):       # 沪市可转债 / 沪市回购
        return 1
    if code.startswith(("12", "15", "16", "18")):  # 深市可转债 / 深市基金
        return 0
    if code[0] in "5679":                   # 沪市基金 / 沪A / 沪市新股 / 沪B
        return 1
    return 0                                # 深A(0/3)、北交所(4/8)、深B(2)


async def _suggest(client: httpx.AsyncClient, keyword: str) -> str | None:
    """Fall back to Eastmoney's symbol search for names and US tickers."""
    try:
        resp = await client.get(
            _SUGGEST,
            params={
                "input": keyword,
                "type": 14,
                "token": "D43BF722C8E33BDC906FB84D85E326E8",
                "count": 5,
            },
        )
        resp.raise_for_status()
        payload = resp.json() or {}
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    items = ((payload.get("QuotationCodeTable") or {}).get("Data")) or []
    for item in items:
        code = item.get("Code")
        market = item.get("MktNum")
        if code and market:
            return f"{market}.{code}"
    return None


# -- formatting --------------------------------------------------------------

def _rank_table(rows: list[dict]) -> list[str]:
    out = [
        "| Code | Name | Last | Chg % | Turnover(亿) | 主力净流入(亿) | 主力占比% |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        out.append(
            f"| {row.get('f12', '')} | {row.get('f14', '')} | {_num(row.get('f2'))} | "
            f"{_pct(row.get('f3'))} | {_yi(row.get('f6'))} | {_yi(row.get('f62'))} | "
            f"{_num(row.get('f184'))} |"
        )
    if len(out) == 2:
        out.append("| - | (endpoint returned no rows) | - | - | - | - | - |")
    return out


def _f(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num


def _num(value: Any) -> str:
    num = _f(value)
    if num is None:
        return "n/a"
    return f"{num:,.2f}" if abs(num) < 1e7 else f"{num:,.0f}"


def _pct(value: Any) -> str:
    num = _f(value)
    return "n/a" if num is None else f"{num:+.2f}%"


def _yi(value: Any) -> str:
    """Render a CNY amount in 亿 (1e8), the unit Chinese market copy uses."""
    num = _f(value)
    return "n/a" if num is None else f"{num / 1e8:,.2f}"


def _ma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _change(last: float | None, reference: float | None) -> float | None:
    if last is None or not reference:
        return None
    return (last - reference) / reference * 100


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime())
