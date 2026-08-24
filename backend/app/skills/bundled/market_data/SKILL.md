---
name: market_data
description: Live quotes, daily history, movers, sector/capital-flow rankings and a cross-market index overview for A-shares (沪深北), Hong Kong, and US stocks, plus FX, gold and crude. Sourced from Eastmoney's public quote endpoints - no API key, and reachable from mainland China. Use this to VERIFY every number before quoting it; never state a price or a percentage that did not come from here.
timeout: 120
parameters:
  type: object
  properties:
    mode:
      type: string
      enum: [overview, quote, history, movers, sectors]
      default: overview
      description: "overview = cross-market index/FX/commodity snapshot. quote = latest prices for the given symbols. history = daily bars + moving averages for one symbol. movers = today's biggest A-share gainers/losers. sectors = 行业/概念板块 ranking with 主力净流入."
    symbols:
      type: array
      items:
        type: string
      default: []
      description: "For mode=quote/history. Accepts 600519, 600519.SH, sh600519, 000001.SZ, 00700.HK, AAPL, or a Chinese name like 贵州茅台. For history only the first symbol is used."
    days:
      type: integer
      default: 60
      minimum: 5
      maximum: 250
      description: "For mode=history: number of trading days of daily bars to return."
    board:
      type: string
      enum: [industry, concept]
      default: industry
      description: "For mode=sectors: 行业板块 (industry) or 概念板块 (concept)."
    rank_by:
      type: string
      enum: [change, main_inflow]
      default: change
      description: "For mode=movers/sectors: rank by percentage change or by 主力净流入 (main capital net inflow)."
    count:
      type: integer
      default: 15
      minimum: 5
      maximum: 50
      description: "For mode=movers/sectors: how many rows per ranking table."
  required: []
---

Wraps Eastmoney's public quote API (`push2`/`push2his`/`searchapi`):

- `overview` - 上证指数, 深证成指, 创业板指, 科创50, 沪深300, 中证500, 北证50,
  恒生指数, 恒生科技, 道指, 纳指, 标普500, 日经225, 离岸人民币, COMEX 黄金, WTI 原油.
- `quote` - last price, change %, open/high/low/prev close, volume, turnover,
  turnover rate, PE(TTM), PB, market cap for each symbol.
- `history` - daily 前复权 bars plus MA5/MA20/MA60, the window high/low, and
  the distance from that high.
- `movers` - top A-share gainers and losers across 沪/深/创/科创/北交所.
- `sectors` - 行业 or 概念 board ranking including 主力净流入 and its share.

Unresolvable symbols and failed calls are reported explicitly; the skill never
substitutes an estimate for a missing quote.
