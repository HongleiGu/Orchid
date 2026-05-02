import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";

const NODE_W = 240;
const NODE_H = 88;

/**
 * Run dagre layered layout over an existing set of React Flow nodes/edges
 * and return new nodes with positions filled in. The original nodes/edges
 * objects are not mutated.
 *
 * Use only when nodes have no meaningful positions yet (initial load of a
 * DAG that came from the backend without editor positions). Once the user
 * has dragged things around, preserve their positions.
 */
export function autoLayout<T extends Record<string, unknown>>(
  nodes: Node<T>[],
  edges: Edge[],
  direction: "LR" | "TB" = "LR",
): Node<T>[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 50, ranksep: 80 });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const dagN = g.node(n.id);
    return {
      ...n,
      position: {
        x: dagN.x - NODE_W / 2,
        y: dagN.y - NODE_H / 2,
      },
    };
  });
}
