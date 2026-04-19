---
name: in_depth_research
description: "Heavyweight: runs an internal research loop (5-10+ searches, citation trails, source evaluation, synthesis) and returns a structured cited report. Expensive — use only when a full report is the deliverable. For quick lookups use multi_search."
parameters:
  type: object
  properties:
    topic:
      type: string
      description: "The research question or topic to investigate."
    depth:
      type: string
      enum: [overview, thorough, exhaustive]
      default: thorough
      description: "Research depth. Overview: 2-3 searches. Thorough: 5-8 searches with cross-referencing. Exhaustive: 10+ searches with source evaluation."
    max_searches:
      type: integer
      default: 5
      description: "Maximum number of web searches to perform."
  required:
    - topic
---

# In-Depth Research

Performs iterative, multi-step web research on a given topic:
1. Initial broad search to map the landscape
2. Identify key subtopics and open questions
3. Targeted deep-dives on each subtopic
4. Cross-reference findings across sources
5. Synthesize into a structured report with citations

Adapted from [ClaWHub in-depth-research](https://clawhub.ai/ivangdavila/in-depth-research).
