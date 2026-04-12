---
name: acl_anthology
description: Search ACL Anthology for NLP/CL conference papers (ACL, EMNLP, NAACL, EACL, CoNLL, etc). Uses the ACL Anthology GitHub data API.
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query.
    max_results:
      type: integer
      default: 10
    venue:
      type: string
      description: "Venue code filter (e.g. 'acl', 'emnlp', 'naacl'). Empty for all."
      default: ""
  required:
    - query
---
