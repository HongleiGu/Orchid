#!/usr/bin/env node
/**
 * Jira CLI — connects to the OR (Orchid) board on hongleigu19.atlassian.net
 *
 * Usage:
 *   npm run jira -- <command> [args]
 *
 * Commands:
 *   board              Show board info
 *   sprints            List sprints (active first)
 *   issues [sprint]    List issues for active sprint (or sprint ID)
 *   issue <KEY>        Show details for a specific issue (e.g. OR-1)
 */

const BASE_URL = "https://hongleigu19.atlassian.net";
const PROJECT_KEY = "OR";
const BOARD_ID = 133;

const token = process.env.JIRA_API_TOKEN;
const EMAIL = process.env.JIRA_EMAIL;

if (!token || !EMAIL) {
  console.error("Error: JIRA_API_TOKEN and JIRA_EMAIL must be set in .env");
  process.exit(1);
}

const auth = Buffer.from(`${EMAIL}:${token}`).toString("base64");

const headers = {
  Authorization: `Basic ${auth}`,
  Accept: "application/json",
};

// ── helpers ──────────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Jira API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

const c = {
  bold: (s: string) => `\x1b[1m${s}\x1b[0m`,
  dim: (s: string) => `\x1b[2m${s}\x1b[0m`,
  green: (s: string) => `\x1b[32m${s}\x1b[0m`,
  yellow: (s: string) => `\x1b[33m${s}\x1b[0m`,
  cyan: (s: string) => `\x1b[36m${s}\x1b[0m`,
  red: (s: string) => `\x1b[31m${s}\x1b[0m`,
};

function statusColor(status: string) {
  const s = status.toLowerCase();
  if (s.includes("done") || s.includes("closed")) return c.green(status);
  if (s.includes("progress") || s.includes("review")) return c.yellow(status);
  if (s.includes("todo") || s.includes("open") || s.includes("backlog")) return c.dim(status);
  return status;
}

// ── commands ─────────────────────────────────────────────────────────────────

async function cmdBoard() {
  const board = await get<{ id: number; name: string; type: string; self: string }>(
    `/rest/agile/1.0/board/${BOARD_ID}`
  );
  console.log(`\n${c.bold("Board")}  ${c.cyan(`#${board.id}`)} — ${board.name}`);
  console.log(`  Type : ${board.type}`);
  console.log(`  URL  : ${BASE_URL}/jira/software/projects/${PROJECT_KEY}/boards/${BOARD_ID}\n`);
}

async function cmdSprints() {
  console.log(`\n${c.yellow("Note:")} This board is a Kanban (simple) board — it does not use sprints.\n`);
  console.log(`  Use ${c.cyan("npm run jira -- issues")} to list all open issues instead.\n`);
}

async function cmdIssues(statusFilter?: string) {
  let jql: string;

  // PROJECT_KEY is quoted because "OR" is a reserved JQL keyword.
  if (statusFilter) {
    jql = `project = "${PROJECT_KEY}" AND status = "${statusFilter}" ORDER BY updated DESC`;
  } else {
    jql = `project = "${PROJECT_KEY}" AND status != Done ORDER BY updated DESC`;
  }

  const data = await get<{
    isLast: boolean;
    issues: Array<{
      key: string;
      fields: {
        summary: string;
        status: { name: string };
        assignee: { displayName: string } | null;
        priority: { name: string } | null;
        issuetype: { name: string };
      };
    }>;
  }>(`/rest/api/3/search/jql?jql=${encodeURIComponent(jql)}&maxResults=50&fields=summary,status,assignee,priority,issuetype`);

  const more = !data.isLast ? c.dim("  (more available)") : "";
  console.log(`\n${c.bold("Issues")}  ${c.dim(`(${data.issues.length} shown${data.isLast ? "" : "+"})`)}${more}\n`);

  if (data.issues.length === 0) {
    console.log("  No issues found.\n");
    return;
  }

  const keyWidth = Math.max(...data.issues.map((i) => i.key.length));

  for (const issue of data.issues) {
    const assignee = issue.fields.assignee?.displayName ?? c.dim("unassigned");
    const status = statusColor(issue.fields.status.name);
    const type = c.dim(issue.fields.issuetype.name);
    console.log(
      `  ${c.cyan(issue.key.padEnd(keyWidth))}  ${status.padEnd(30)}  ${issue.fields.summary.slice(0, 60)}  ${c.dim("→")} ${assignee}  ${type}`
    );
  }
  console.log();
}

async function cmdIssue(key: string) {
  const normalised = key.toUpperCase().startsWith(PROJECT_KEY) ? key.toUpperCase() : `${PROJECT_KEY}-${key}`;

  const issue = await get<{
    key: string;
    fields: {
      summary: string;
      description: { content?: unknown[] } | null;
      status: { name: string };
      assignee: { displayName: string; emailAddress: string } | null;
      reporter: { displayName: string } | null;
      priority: { name: string } | null;
      issuetype: { name: string };
      created: string;
      updated: string;
      labels: string[];
      comment: { total: number };
    };
  }>(`/rest/api/3/issue/${normalised}`);

  const f = issue.fields;
  console.log(`\n${c.bold(issue.key)}  ${c.dim(f.issuetype.name)}`);
  console.log(`${c.bold(f.summary)}\n`);
  console.log(`  Status   : ${statusColor(f.status.name)}`);
  console.log(`  Priority : ${f.priority?.name ?? c.dim("none")}`);
  console.log(`  Assignee : ${f.assignee?.displayName ?? c.dim("unassigned")}`);
  console.log(`  Reporter : ${f.reporter?.displayName ?? c.dim("unknown")}`);
  console.log(`  Labels   : ${f.labels.length ? f.labels.join(", ") : c.dim("none")}`);
  console.log(`  Comments : ${f.comment.total}`);
  console.log(`  Created  : ${f.created.slice(0, 10)}`);
  console.log(`  Updated  : ${f.updated.slice(0, 10)}`);
  console.log(`  URL      : ${BASE_URL}/browse/${issue.key}\n`);
}

function help() {
  console.log(`
${c.bold("Jira CLI")}  — OR (Orchid) board

${c.bold("Usage:")}
  npm run jira -- <command> [args]

${c.bold("Commands:")}
  board                Show board info
  issues               List all open issues (sorted by updated)
  issues <status>      Filter by status (e.g. "In Progress", "To Do")
  issue <OR-N>         Show issue details
`);
}

// ── dispatch ─────────────────────────────────────────────────────────────────

const [cmd, arg] = process.argv.slice(2).filter((a) => a !== "--");

(async () => {
  try {
    switch (cmd) {
      case "board":
        await cmdBoard();
        break;
      case "sprints":
        await cmdSprints();
        break;
      case "issues":
        await cmdIssues(arg);
        break;
      case "issue":
        if (!arg) { console.error(`Usage: jira issue <${PROJECT_KEY}-N>`); process.exit(1); }
        await cmdIssue(arg);
        break;
      default:
        help();
    }
  } catch (err) {
    console.error(c.red(`\nError: ${(err as Error).message}\n`));
    process.exit(1);
  }
})();
