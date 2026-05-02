---
name: http_request
description: Raw HTTP GET/POST/PUT/PATCH/DELETE for calling APIs without a dedicated skill. For HTML pages prefer web_reader (it strips boilerplate). For web search prefer multi_search.
timeout: 60
parameters:
  type: object
  properties:
    url:
      type: string
      description: The target URL.
    method:
      type: string
      enum: [GET, POST, PUT, PATCH, DELETE]
      default: GET
    body:
      type: object
      description: JSON body for POST/PUT/PATCH requests.
    headers:
      type: object
      description: Additional HTTP headers.
  required: [url]
---

Raw HTTP client. Returns the response body truncated to 8000 chars.
