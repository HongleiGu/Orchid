/**
 * One-off script: seeds the OR (Orchid) Jira board with epics and stories.
 * Run once: pnpm tsx --env-file=.env scripts/seed-jira.ts
 *
 * The ticket plan below is the Orchid roadmap: auto-research reliability, the
 * DAG editor's control flow, vault RAG (pgvector), exposing backend APIs
 * (ComfyUI), and a foundation-refactor catch-all. Epics = themes, tasks = the
 * concrete work under each.
 */

const BASE_URL = "https://hongleigu19.atlassian.net";
const PROJECT_KEY = "OR";
const EMAIL = process.env.JIRA_EMAIL!;
const TOKEN = process.env.JIRA_API_TOKEN!;

const ISSUE_TYPES = {
  epic:  "10185", // 长篇故事 (hierarchy 1)
  task:  "10187", // 任务 (hierarchy 0 — used for stories under epics)
};

const auth = Buffer.from(`${EMAIL}:${TOKEN}`).toString("base64");
const headers = {
  Authorization: `Basic ${auth}`,
  "Content-Type": "application/json",
  Accept: "application/json",
};

function adf(text: string) {
  return {
    type: "doc",
    version: 1,
    content: [{ type: "paragraph", content: [{ type: "text", text }] }],
  };
}

async function createIssue(fields: Record<string, unknown>): Promise<{ key: string }> {
  const res = await fetch(`${BASE_URL}/rest/api/3/issue`, {
    method: "POST",
    headers,
    body: JSON.stringify({ fields: { project: { key: PROJECT_KEY }, ...fields } }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json() as Promise<{ key: string }>;
}

const c = {
  bold: (s: string) => `\x1b[1m${s}\x1b[0m`,
  green: (s: string) => `\x1b[32m${s}\x1b[0m`,
  cyan: (s: string) => `\x1b[36m${s}\x1b[0m`,
  dim: (s: string) => `\x1b[2m${s}\x1b[0m`,
};

// ── Ticket plan ───────────────────────────────────────────────────────────────

const EPICS: Array<{
  summary: string;
  description: string;
  stories: Array<{ summary: string; description: string }>;
}> = [
  {
    summary: "Auto-research reliability & paper pipeline",
    description:
      "The main story: make the autonomous research + paper pipeline actually close its loop and produce trustworthy artifacts. Today the DAG engine (backend/app/core/dag.py) is a strict topological walk with no loops, so REFINE/PIVOT dead-ends instead of re-running. This epic adds real iteration, hardens the in-flight consensus/contract engine, and enforces honest experiment execution.",
    stories: [
      {
        summary: "Cyclic-edge loop support in the DAG engine",
        description:
          "Replace the topo-only frontier walk in backend/app/core/dag.py so a back-edge to an earlier node re-executes it. Iteration budget lives on the loop-closing edge as max_iterations; add a DAG-run-level global ceiling (config, default ~25 total node-executions) as a runaway backstop. There is existing branch/contract logic here that may need reworking. First ticket of the epic — Epic 2's loop UI depends on it.",
      },
      {
        summary: "Fix conditional branch-merge in-degree bug",
        description:
          "Failed conditional edges currently do not decrement a target's in-degree (documented at dag.py:22-26), so any node with mixed conditional + unconditional in-edges hangs — which is why the example DAGs need duplicate terminal nodes. Fix the in-degree accounting so branches can merge into a single downstream node, and remove the duplicate-terminal-node workaround from examples/autonomous-researchclaw-dag.json.",
      },
      {
        summary: "Finish & harden the consensus node engine",
        description:
          "Complete the in-progress consensus engine (_run_consensus in dag.py): per-trajectory timeout handling, surfacing the vote tally in run metadata/UI, and the no-majority retry/exhaustion policy. Add tests covering majority-reached, no-majority, and timed-out-trajectory cases.",
      },
      {
        summary: "Contract check-engine test suite + docs",
        description:
          "The contract engine supports ~20 check types (contains, regex, json_parse, tool_called, llm_judge, needs_human, requires_secret, evidence_level, ...) with no tests. Add a unit-test suite per check type plus escalation policies (retry/stop/human_review/annotate, on_blocked, on_exhausted), and document the contract schema for DAG authors.",
      },
      {
        summary: "Honest experiment execution path",
        description:
          "Stop dry-run / stdlib-only / simulated results from proceeding to paper-writing as if they were evidence. Provide a real (non-stdlib) execution path or wire the blocked_needs_* contract statuses to human-review so missing credentials/budget/network halt cleanly instead of being framed as empirical results.",
      },
      {
        summary: "Close the loop in the researchclaw DAG + end-to-end run",
        description:
          "Rework examples/autonomous-researchclaw-dag.json so a REFINE/PIVOT decision from the judge cycles back into design/execute (using the new cyclic-edge support) instead of dead-ending in finalize_rethink. Then do an end-to-end verification run and confirm the loop, gates, and vault archival all behave.",
      },
    ],
  },
  {
    summary: "DAG editor: control flow & authoring",
    description:
      "Make the visual DAG editor (frontend/src/app/tasks/[id]/dag/page.tsx) a first-class authoring surface. Today a user can add agent nodes, draw edges, and edit an edge's raw Python condition — but cannot author loops, contracts, or node inputs/outputs, and must create the task before the editor exists. This epic closes that gap so users can build real DAGs directly.",
    stories: [
      {
        summary: "Loop authoring in the editor",
        description:
          "Let a user draw a back-edge to an earlier node and set its max_iterations, visualising the cycle. Pairs with the engine's cyclic-edge support from Epic 1.",
      },
      {
        summary: "Node contract editor panel",
        description:
          "Contracts are currently JSON-import-only. Add a UI panel to author a node's contract: checks, consensus (n/min_agree/agree_on), retries, and on_fail/on_blocked policies — persisted into the node's workflow_config.",
      },
      {
        summary: "Guided condition / branch builder",
        description:
          "Replace the raw Python-expression textarea in the EdgeInspector with a guided builder (field, operator, value against output.content/metadata) that renders to the same `if` expression, with branch visualisation on the canvas.",
      },
      {
        summary: "Per-node inputs/outputs editor",
        description:
          "The node inputs/outputs fields exist in the schema and survive import/export but have no UI. Add editing for per-node inputs and declared outputs so authors can shape data handoff without editing JSON.",
      },
      {
        summary: "Create-a-DAG-from-scratch flow",
        description:
          "Remove the two-step 'create the task first, then open the editor' dance (tasks/page.tsx leaves the config empty on create). Let a user start a new DAG directly and save nodes/edges/entry in one flow.",
      },
      {
        summary: "Test-run-one-node from the editor",
        description:
          "Add the ability to run a single node with sample/upstream inputs and inspect its output and contract result, without executing the whole DAG — the core of the run-to-edit loop.",
      },
    ],
  },
  {
    summary: "Vault RAG (pgvector)",
    description:
      "Upgrade the vault from keyword-only search to real semantic retrieval on Postgres/pgvector. Today vault_search does substring scoring, the .orchid/index.json is written but never read, and there is no embedding client or vector store anywhere in the repo — this is greenfield on both storage and retrieval.",
    stories: [
      {
        summary: "Embedding client abstraction + config",
        description:
          "Introduce an embedding client (provider/model configurable, mirroring the model_client pattern) plus config in backend/app/config.py. No embedding path exists today; the current model_client is chat-completion only.",
      },
      {
        summary: "pgvector store: schema + Alembic migration",
        description:
          "Add a pgvector extension + a table for vault chunk embeddings (project, filename, chunk, vector, metadata) with an Alembic migration. Postgres is already the production DB.",
      },
      {
        summary: "Embed-on-write + markdown chunking",
        description:
          "On vault_write, chunk the .md content and generate/store embeddings alongside the existing file write and index update. Define the chunking strategy (headings/size) for markdown notes.",
      },
      {
        summary: "Semantic / hybrid vault_search",
        description:
          "Replace or augment the keyword _score path in vault_search with vector similarity over pgvector, keeping keyword as a fallback and finally reading the .orchid index. Return ranked chunks with source paths.",
      },
      {
        summary: "Wire research agents to semantic retrieval",
        description:
          "Point the scope/synthesis research agents at the semantic vault_search so prior-notes recall in the auto-research pipeline is retrieval-quality rather than substring-match.",
      },
    ],
  },
  {
    summary: "Expose backend APIs (ComfyUI & friends)",
    description:
      "Give agents a clean path to call external backend services like ComfyUI. Skills already run out-of-process in the skill-runner container and can make httpx calls, but the contract is string-return, request/response only (no streaming), with an 8k-char cap in the generic http_request skill — which doesn't fit ComfyUI's submit/poll/binary-image flow.",
    stories: [
      {
        summary: "Polling / long-running skill pattern",
        description:
          "Define and implement a reusable pattern for skills that call async services which enqueue work and must be polled to completion (e.g. ComfyUI's prompt queue), within the runner's request/response + timeout contract.",
      },
      {
        summary: "Binary / image artifact handoff to the vault",
        description:
          "Skills return strings and the generic http_request caps output at 8k chars. Add a standard way to hand binary/image results (base64 or a written vault assets/ path) back from a skill so image outputs survive instead of being truncated.",
      },
      {
        summary: "ComfyUI skill",
        description:
          "Author a dedicated bundled/marketplace skill that submits a ComfyUI prompt/workflow, polls the queue to completion, and fetches the resulting image(s), using the polling pattern and artifact handoff above. Secrets/host via env vars.",
      },
      {
        summary: "Backend-API adapter template in the skill-writer",
        description:
          "Add a reusable 'call an internal backend API' template to the skill-writer so new service integrations (beyond ComfyUI) are scaffolded consistently, including the network-egress and secret-handling contract for external-service skills.",
      },
    ],
  },
  {
    summary: "Foundation refactor",
    description:
      "Catch-all for structural cleanups surfaced while building the above. Kept as a single tracking epic; break out concrete tickets as needs become clear.",
    stories: [
      {
        summary: "Refactor & harden DAG schema and workflow-maker",
        description:
          "Formalize the DAG node/edge shape as Pydantic models (they are free-form dicts today, defined only by docstrings and TS types), and make the workflow-maker emit contracts and loops rather than minimal name/agent-only nodes. Track further refactors here as they surface.",
      },
    ],
  },
];

// ── Execution ─────────────────────────────────────────────────────────────────
// Pass --dry-run to print the plan without creating anything.
// Pass --stories-only <OR-N,OR-N,...> to skip epic creation and attach tasks
// to pre-existing epic keys in order.
// Example: pnpm tsx --env-file=.env scripts/seed-jira.ts --stories-only OR-1,OR-8,OR-14,OR-19,OR-24

const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const storiesOnlyIdx = args.indexOf("--stories-only");
const existingEpicKeys: string[] =
  storiesOnlyIdx !== -1 ? (args[storiesOnlyIdx + 1] ?? "").split(",") : [];
const storiesOnly = storiesOnlyIdx !== -1;

(async () => {
  const epicTotal = EPICS.length;
  const taskTotal = EPICS.reduce((n, e) => n + e.stories.length, 0);
  if (dryRun) {
    console.log(`\n${c.bold(`DRY RUN`)} — plan for project ${PROJECT_KEY} (${epicTotal} epics, ${taskTotal} tasks). Nothing will be created.\n`);
    for (const epic of EPICS) {
      console.log(`${c.bold("Epic")}  ${c.cyan(epic.summary)}`);
      for (const story of epic.stories) console.log(`  ${c.dim("Task")}  ${story.summary}`);
      console.log();
    }
    console.log(`${c.green("OK.")} Re-run without --dry-run to create these on the ${PROJECT_KEY} board.\n`);
    return;
  }

  console.log(`\nSeeding ${PROJECT_KEY} Jira board${storiesOnly ? " (tasks only)" : ""}...\n`);
  let epicCount = 0;
  let taskCount = 0;

  for (let i = 0; i < EPICS.length; i++) {
    const epic = EPICS[i];
    let epicKey: string;

    if (storiesOnly) {
      epicKey = existingEpicKeys[i];
      if (!epicKey) { console.error(`No epic key provided for index ${i} (${epic.summary})`); continue; }
      console.log(`${c.bold("Epic")}  ${c.cyan(epicKey)}  ${epic.summary} ${c.dim("(existing)")}`);
    } else {
      try {
        const res = await createIssue({
          summary: epic.summary,
          description: adf(epic.description),
          issuetype: { id: ISSUE_TYPES.epic },
        });
        epicKey = res.key;
        console.log(`${c.bold("Epic")}  ${c.cyan(epicKey)}  ${epic.summary}`);
        epicCount++;
      } catch (err) {
        console.error(`${c.bold("Epic")}  FAILED  ${epic.summary}: ${(err as Error).message}`);
        continue;
      }
    }

    for (const story of epic.stories) {
      try {
        const { key: taskKey } = await createIssue({
          summary: story.summary,
          description: adf(story.description),
          issuetype: { id: ISSUE_TYPES.task },
          parent: { key: epicKey },
        });
        console.log(`  ${c.dim("Task")}  ${c.cyan(taskKey)}  ${story.summary}`);
        taskCount++;
      } catch (err) {
        console.error(`  ${c.dim("Task")}  FAILED  ${story.summary}: ${(err as Error).message}`);
      }
    }
  }

  console.log(
    `\n${c.green("Done.")}  ${storiesOnly ? "" : `Created ${epicCount} epic(s) and `}${taskCount} task(s).\n`
  );
})();
