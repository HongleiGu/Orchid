---
name: gmail_send
description: Send an email via Gmail. Supports plain text, HTML, and file attachments. Attachments are resolved as vault paths. Requires Gmail OAuth to be set up first (visit /api/v1/gmail/auth).
timeout: 60
parameters:
  type: object
  properties:
    to:
      type: string
      description: Recipient email address.
    subject:
      type: string
    body:
      type: string
      description: Email body content (plain text, markdown, or HTML).
    html:
      type: boolean
      default: false
      description: Whether body is HTML. Markdown is auto-detected otherwise.
    cc:
      type: string
      default: ""
      description: CC recipients (comma-separated).
    attachments:
      type: string
      default: ""
      description: "Comma-separated vault-relative paths to attach. Absolute paths also work."
  required: [to, subject, body]
---
