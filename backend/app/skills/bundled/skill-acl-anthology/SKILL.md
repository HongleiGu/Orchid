---
name: acl_anthology
description: ACL/EMNLP/NAACL/EACL/CoNLL papers only. Use when the topic is squarely NLP or computational linguistics; for broader CS or cross-field work prefer dblp or openalex.
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
