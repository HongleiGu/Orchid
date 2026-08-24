---
name: news_feeds
description: Pull the latest headlines straight from primary news sources - Chinese realtime market flash wires (华尔街见闻/新浪财经7x24/金十/东方财富), Chinese finance media, and global market/macro sources (Chinese-language global wires plus CNBC, MarketWatch, Yahoo Finance, Investing.com, FT, SCMP, Federal Reserve, ECB). No API key required. Returns a time-sorted, deduplicated headline feed with source attribution and per-source fetch diagnostics.
timeout: 120
parameters:
  type: object
  properties:
    bundle:
      type: string
      enum: [cn_flash, cn_finance, global_markets, global_macro, all]
      default: cn_flash
      description: "Which curated source set to pull. 'all' pulls every bundle (slower; use a larger limit)."
    limit:
      type: integer
      default: 40
      minimum: 5
      maximum: 150
      description: "Maximum headlines returned after merging and deduplication."
    hours:
      type: integer
      default: 24
      minimum: 1
      maximum: 168
      description: "Only keep items published within this many hours (items with no parseable timestamp are kept and flagged)."
    keywords:
      type: array
      items:
        type: string
      default: []
      description: "Optional filter - keep only headlines containing at least one of these substrings (Chinese or English)."
    extra_feeds:
      type: array
      items:
        type: string
      default: []
      description: "Extra RSS/Atom feed URLs to merge in alongside the bundle."
    cn_accessible_only:
      type: boolean
      default: false
      description: "Set true when the runner sits inside mainland China without a proxy: skips sources known to be unreachable there (FT, Yahoo, Fed, ECB, SCMP, Investing.com)."
  required: []
---

Fetches every source in the chosen bundle concurrently, parses RSS/Atom via the
stdlib XML parser and each JSON wire via its own adapter, normalizes items to
`(published, source, title, summary, url)`, filters by time window and
keywords, deduplicates by normalized title, and sorts newest first.

Every source is tagged with whether it is reachable from mainland China without
a proxy. Sources that fail are listed in a diagnostics section with their error
so a caller can distinguish "blocked or down" from "nothing published" - never
report silence as calm markets.
