---
name: wechat_upload_image
description: Upload an image to WeChat for use inside an Official Account article. Returns a URL you can embed in HTML as <img src='...'>. Input is a vault-relative (or absolute) path to a local image file.
timeout: 60
parameters:
  type: object
  properties:
    path:
      type: string
      description: "Vault-relative path or absolute path."
  required: [path]
---
