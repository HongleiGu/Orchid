---
name: wechat_followers
description: List followers of the WeChat Official Account. Returns OpenIDs.
timeout: 30
parameters:
  type: object
  properties:
    next_openid:
      type: string
      default: ""
      description: Pagination cursor. Empty for first page.
---
