"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, LayoutGrid, Plus, Save, Trash2 } from "lucide-react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type EdgeMouseHandler,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { Button, Card, Input, Select, Textarea } from "@/components/ui";
import { useAgents, useTasks, useUpdateTask } from "@/lib/hooks";
import { autoLayout } from "@/lib/dagLayout";
import type {
  Agent,
  DagEdgeConfig,
  DagNodeConfig,
  DagWorkflowConfig,
  Task,
} from "@/lib/types";

// ── Node payload type ─────────────────────────────────────────────────────────

type AgentNodeData = {
  label: string;            // node.name (the unique id used on the wire)
  agentId: string;
  agentName: string;
} & Record<string, unknown>;
type AgentNode = Node<AgentNodeData>;

// ── Custom node renderer ──────────────────────────────────────────────────────

function AgentNodeView({ data, selected }: NodeProps<AgentNode>) {
  return (
    <div
      className={`rounded-lg border bg-card px-3 py-2 shadow-sm min-w-45 ${
        selected ? "border-accent ring-2 ring-accent/30" : "border-border"
      }`}
    >
      <Handle type="target" position={Position.Left} className="bg-accent!" />
      <div className="text-xs uppercase tracking-wide text-muted">{data.label}</div>
      <div className="text-sm font-medium truncate">{data.agentName || "(no agent)"}</div>
      <Handle type="source" position={Position.Right} className="bg-accent!" />
    </div>
  );
}

const NODE_TYPES = { agent: AgentNodeView };

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DagEditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <ReactFlowProvider>
      <DagEditorInner params={params} />
    </ReactFlowProvider>
  );
}

function DagEditorInner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const tasksQuery = useTasks(1);
  const agentsQuery = useAgents(1);
  const update = useUpdateTask();

  const task: Task | undefined = useMemo(
    () => tasksQuery.data?.data.find((t) => t.id === id),
    [tasksQuery.data, id],
  );
  const agents: Agent[] = useMemo(
    () => agentsQuery.data?.data ?? [],
    [agentsQuery.data],
  );
  const agentsById = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.id, a])),
    [agents],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<AgentNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const [selectedNode, setSelectedNode] = useState<AgentNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [entry, setEntry] = useState<string>("");
  const [autoSave, setAutoSave] = useState<boolean>(true);

  // Hydrate from backend once the task arrives. This is the textbook
  // "sync external async data into local editable state" case — the
  // alternative (initial-state via useMemo) doesn't work because the task
  // isn't available on first render.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current || !task) return;
    if (task.workflow_type !== "dag") {
      toast.error("This task is not a DAG workflow.");
      router.push("/tasks");
      return;
    }
    hydratedRef.current = true;

    const cfg = (task.workflow_config ?? {}) as unknown as DagWorkflowConfig;
    const cfgNodes: DagNodeConfig[] = cfg.nodes ?? [];
    const cfgEdges: DagEdgeConfig[] = cfg.edges ?? [];

    const flowNodes: AgentNode[] = cfgNodes.map((n, i) => ({
      id: n.name,
      type: "agent",
      position: n.position ?? { x: i * 280, y: 0 },
      data: {
        label: n.name,
        agentId: n.agent_id,
        agentName: agentsById[n.agent_id]?.name ?? "(missing agent)",
      },
    }));
    const flowEdges: Edge[] = cfgEdges.map((e, i) => ({
      id: `e-${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      label: e.if ? "if" : undefined,
      data: { if: e.if ?? "" },
      type: "default",
    }));

    const positioned = cfgNodes.every((n) => n.position)
      ? flowNodes
      : autoLayout(flowNodes, flowEdges);

    /* eslint-disable react-hooks/set-state-in-effect */
    setNodes(positioned);
    setEdges(flowEdges);
    setEntry(cfg.entry ?? cfgNodes[0]?.name ?? "");
    setAutoSave(cfg.auto_save !== false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [task, agentsById, setNodes, setEdges, router]);

  // ── Editing handlers ────────────────────────────────────────────────────────

  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      setEdges((es) =>
        addEdge(
          {
            ...conn,
            id: `e-${conn.source}-${conn.target}-${Date.now()}`,
            data: { if: "" },
          },
          es,
        ),
      );
    },
    [setEdges],
  );

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    setSelectedNode(node as AgentNode);
    setSelectedEdge(null);
  }, []);

  const onEdgeClick: EdgeMouseHandler = useCallback((_, edge) => {
    setSelectedEdge(edge);
    setSelectedNode(null);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    setSelectedEdge(null);
  }, []);

  function addNodeForAgent(agent: Agent) {
    const taken = new Set(nodes.map((n) => n.id));
    let name = agent.name;
    let i = 2;
    while (taken.has(name)) name = `${agent.name}-${i++}`;
    // Deterministic offset by node count — keeps layouts reproducible and
    // avoids the impure-render-fn lint.
    const slot = nodes.length;
    const newNode: AgentNode = {
      id: name,
      type: "agent",
      position: { x: 80 + (slot % 4) * 80, y: 80 + Math.floor(slot / 4) * 100 },
      data: { label: name, agentId: agent.id, agentName: agent.name },
    };
    setNodes((ns) => [...ns, newNode]);
    if (!entry) setEntry(name);
  }

  function deleteSelected() {
    if (selectedNode) {
      const id = selectedNode.id;
      setNodes((ns) => ns.filter((n) => n.id !== id));
      setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
      if (entry === id) setEntry("");
      setSelectedNode(null);
    } else if (selectedEdge) {
      const id = selectedEdge.id;
      setEdges((es) => es.filter((e) => e.id !== id));
      setSelectedEdge(null);
    }
  }

  function relayout() {
    setNodes((ns) => autoLayout(ns, edges));
  }

  // ── Inspector mutations ─────────────────────────────────────────────────────

  function renameNode(oldName: string, newName: string) {
    if (!newName || newName === oldName) return;
    if (nodes.some((n) => n.id === newName)) {
      toast.error(`Node "${newName}" already exists`);
      return;
    }
    setNodes((ns) =>
      ns.map((n) =>
        n.id === oldName
          ? { ...n, id: newName, data: { ...n.data, label: newName } }
          : n,
      ),
    );
    setEdges((es) =>
      es.map((e) => ({
        ...e,
        source: e.source === oldName ? newName : e.source,
        target: e.target === oldName ? newName : e.target,
      })),
    );
    if (entry === oldName) setEntry(newName);
    setSelectedNode((n) =>
      n?.id === oldName
        ? ({ ...n, id: newName, data: { ...n.data, label: newName } } as AgentNode)
        : n,
    );
  }

  function setNodeAgent(nodeId: string, agentId: string) {
    const ag = agentsById[agentId];
    setNodes((ns) =>
      ns.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              data: {
                ...n.data,
                agentId,
                agentName: ag?.name ?? "(missing agent)",
              },
            }
          : n,
      ),
    );
    setSelectedNode((n) =>
      n?.id === nodeId
        ? {
            ...n,
            data: {
              ...n.data,
              agentId,
              agentName: ag?.name ?? "(missing agent)",
            },
          }
        : n,
    );
  }

  function setEdgeCondition(edgeId: string, expr: string) {
    setEdges((es) =>
      es.map((e) =>
        e.id === edgeId
          ? { ...e, label: expr ? "if" : undefined, data: { ...(e.data ?? {}), if: expr } }
          : e,
      ),
    );
    setSelectedEdge((e) =>
      e?.id === edgeId
        ? { ...e, label: expr ? "if" : undefined, data: { ...(e.data ?? {}), if: expr } }
        : e,
    );
  }

  // ── Save ────────────────────────────────────────────────────────────────────

  async function save() {
    if (!task) return;
    if (nodes.length === 0) {
      toast.error("Add at least one node before saving");
      return;
    }
    if (!entry) {
      toast.error("Pick an entry node");
      return;
    }

    const cfg: DagWorkflowConfig = {
      nodes: nodes.map((n) => ({
        name: n.id,
        agent_id: n.data.agentId,
        position: n.position,
      })),
      edges: edges.map((e) => {
        const ifExpr = ((e.data ?? {}) as { if?: string }).if;
        return {
          source: e.source,
          target: e.target,
          ...(ifExpr ? { if: ifExpr } : {}),
        };
      }),
      entry,
      auto_save: autoSave,
    };

    try {
      await update.mutateAsync({
        id: task.id,
        body: { workflow_config: cfg as unknown as Record<string, unknown> },
      });
      toast.success("DAG saved");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (tasksQuery.isLoading || !task) {
    return <div className="p-6 text-sm text-muted">Loading…</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-0px)]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2 bg-card">
        <Link href="/tasks" className="text-muted hover:text-foreground">
          <ArrowLeft size={18} />
        </Link>
        <div className="font-semibold text-sm">{task.name}</div>
        <span className="text-xs text-muted">DAG editor</span>
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={relayout}>
          <LayoutGrid size={14} className="mr-1.5" /> Auto-layout
        </Button>
        <Button size="sm" onClick={save} disabled={update.isPending}>
          <Save size={14} className="mr-1.5" /> Save
        </Button>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Left rail: agents */}
        <div className="w-56 shrink-0 border-r border-border bg-card overflow-auto">
          <div className="p-3 text-xs font-semibold uppercase tracking-wide text-muted">
            Agents
          </div>
          <div className="px-2 pb-2 space-y-1">
            {agents.map((a) => (
              <button
                key={a.id}
                onClick={() => addNodeForAgent(a)}
                className="w-full flex items-center justify-between text-left text-sm rounded-md px-2 py-1.5 hover:bg-accent/5"
              >
                <span className="truncate">{a.name}</span>
                <Plus size={14} className="text-muted shrink-0" />
              </button>
            ))}
            {agents.length === 0 && (
              <div className="text-xs text-muted px-2 py-2">
                No agents — create one first.
              </div>
            )}
          </div>
        </div>

        {/* Canvas */}
        <div className="flex-1 min-w-0 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={16} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>

        {/* Right rail: inspector */}
        <div className="w-72 shrink-0 border-l border-border bg-card overflow-auto p-4 space-y-4">
          {selectedNode ? (
            <NodeInspector
              key={selectedNode.id}
              node={selectedNode}
              agents={agents}
              isEntry={entry === selectedNode.id}
              onRename={(name) => renameNode(selectedNode.id, name)}
              onAgentChange={(aid) => setNodeAgent(selectedNode.id, aid)}
              onMakeEntry={() => setEntry(selectedNode.id)}
              onDelete={deleteSelected}
            />
          ) : selectedEdge ? (
            <EdgeInspector
              key={selectedEdge.id}
              edge={selectedEdge}
              onConditionChange={(expr) => setEdgeCondition(selectedEdge.id, expr)}
              onDelete={deleteSelected}
            />
          ) : (
            <CanvasInspector
              entry={entry}
              entryOptions={nodes.map((n) => n.id)}
              onEntryChange={setEntry}
              autoSave={autoSave}
              onAutoSaveChange={setAutoSave}
              nodeCount={nodes.length}
              edgeCount={edges.length}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Inspector panels ──────────────────────────────────────────────────────────

function NodeInspector({
  node,
  agents,
  isEntry,
  onRename,
  onAgentChange,
  onMakeEntry,
  onDelete,
}: {
  node: AgentNode;
  agents: Agent[];
  isEntry: boolean;
  onRename: (name: string) => void;
  onAgentChange: (id: string) => void;
  onMakeEntry: () => void;
  onDelete: () => void;
}) {
  // The parent passes a fresh `key` whenever the selected node changes, so
  // this component remounts and `useState`'s initial value is always correct.
  const [name, setName] = useState(node.id);

  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-muted mb-3">
        Node
      </div>
      <Card className="space-y-3">
        <div>
          <label className="text-xs text-muted">Name</label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => onRename(name)}
          />
        </div>
        <div>
          <label className="text-xs text-muted">Agent</label>
          <Select
            value={node.data.agentId}
            onChange={(e) => onAgentChange(e.target.value)}
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </div>
        <Button
          variant={isEntry ? "secondary" : "ghost"}
          size="sm"
          className="w-full"
          onClick={onMakeEntry}
          disabled={isEntry}
        >
          {isEntry ? "Entry node" : "Set as entry"}
        </Button>
        <Button variant="danger" size="sm" className="w-full" onClick={onDelete}>
          <Trash2 size={14} className="mr-1.5" /> Delete node
        </Button>
      </Card>
    </div>
  );
}

function EdgeInspector({
  edge,
  onConditionChange,
  onDelete,
}: {
  edge: Edge;
  onConditionChange: (expr: string) => void;
  onDelete: () => void;
}) {
  // Same remount trick: parent keys this component on edge.id.
  const initial = ((edge.data ?? {}) as { if?: string }).if ?? "";
  const [expr, setExpr] = useState(initial);

  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-muted mb-3">
        Edge
      </div>
      <Card className="space-y-3">
        <div className="text-xs text-muted">
          {edge.source} → {edge.target}
        </div>
        <div>
          <label className="text-xs text-muted">
            Condition (Python expression, runs against <code>output</code>)
          </label>
          <Textarea
            value={expr}
            onChange={(e) => setExpr(e.target.value)}
            onBlur={() => onConditionChange(expr)}
            placeholder='"yes" in output.content.lower()'
            className="font-mono text-xs"
          />
          <div className="text-xs text-muted mt-1">
            Empty = always fire. Available:{" "}
            <code>output.content</code>, <code>output.metadata</code>.
          </div>
        </div>
        <Button variant="danger" size="sm" className="w-full" onClick={onDelete}>
          <Trash2 size={14} className="mr-1.5" /> Delete edge
        </Button>
      </Card>
    </div>
  );
}

function CanvasInspector({
  entry,
  entryOptions,
  onEntryChange,
  autoSave,
  onAutoSaveChange,
  nodeCount,
  edgeCount,
}: {
  entry: string;
  entryOptions: string[];
  onEntryChange: (v: string) => void;
  autoSave: boolean;
  onAutoSaveChange: (v: boolean) => void;
  nodeCount: number;
  edgeCount: number;
}) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-muted mb-3">
        DAG
      </div>
      <Card className="space-y-3">
        <div className="text-xs text-muted">
          {nodeCount} node{nodeCount === 1 ? "" : "s"}, {edgeCount} edge
          {edgeCount === 1 ? "" : "s"}
        </div>
        <div>
          <label className="text-xs text-muted">Entry node</label>
          <Select
            value={entry}
            onChange={(e) => onEntryChange(e.target.value)}
          >
            <option value="">— pick —</option>
            {entryOptions.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoSave}
            onChange={(e) => onAutoSaveChange(e.target.checked)}
          />
          Auto-save run output to vault
        </label>
        <div className="text-xs text-muted">
          Click a node or edge to edit it. Drag from a node&apos;s right
          handle to another node&apos;s left handle to connect.
        </div>
      </Card>
    </div>
  );
}
