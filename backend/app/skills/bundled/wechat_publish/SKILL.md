---
name: wechat_publish
description: Publish an article to WeChat Official Account. Creates a draft article and optionally publishes it immediately. Content can be plain text, markdown, or HTML. Markdown is auto-converted to HTML.
timeout: 90
parameters:
  type: object
  properties:
    title:
      type: string
    content:
      type: string
      description: Article body. Can be markdown, plain text, or HTML.
    author:
      type: string
      default: Orchid AI
    digest:
      type: string
      default: ""
      description: Brief summary shown in feed (max 120 chars). Auto-generated if empty.
    publish:
      type: boolean
      default: false
      description: If true, publish immediately. If false, save as draft only.
  required: [title, content]
---

Requires WECHAT_APP_ID and WECHAT_APP_SECRET in env.
