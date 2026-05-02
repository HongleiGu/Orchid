---
name: gmail_read
description: Read recent emails from Gmail inbox. Returns subject, sender, and snippet for each message.
timeout: 60
parameters:
  type: object
  properties:
    query:
      type: string
      default: ""
      description: "Gmail search query (e.g. 'from:alice', 'is:unread', 'subject:report')."
    max_results:
      type: integer
      default: 5
---
