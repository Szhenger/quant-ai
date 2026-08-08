import { createContext, useCallback, useContext, useEffect, useState } from "react";
import ReactFlow, {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  Handle,
  Position,
  ReactFlowProvider,
  useReactFlow,
} from "reactflow";
import type {
  Connection,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  NodeProps,
  NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import api from "../api/client";
import { extractError } from "../api/errors";
import type { IndicatorCatalog } from "../api/types";

interface StrategyGraphBuilderProps {
  onCreated: () => void;
}

interface AssetData {
  ticker: string;
}
interface QuantData {
  indicator: string;
  operator: string;
  value: string;
  params: Record<string, unknown>;
}
interface AiData {
  prompt: string;
}

const CatalogContext = createContext<IndicatorCatalog | null>(null);

const INITIAL_NODES: Node[] = [
  { id: "asset-1", type: "asset", position: { x: 0, y: 60 }, data: { ticker: "AAPL" } },
  {
    id: "quant-1",
    type: "quant",
    position: { x: 280, y: 20 },
    data: { indicator: "RSI", operator: "<", value: "30", params: {} },
  },
  {
    id: "ai-1",
    type: "ai",
    position: { x: 620, y: 60 },
    data: { prompt: "Confirm this is a genuine oversold entry, not a falling knife." },
  },
];

const INITIAL_EDGES: Edge[] = [
  { id: "e-asset-quant", source: "asset-1", target: "quant-1" },
  { id: "e-quant-ai", source: "quant-1", target: "ai-1" },
];

function useUpdateNodeData<T>(id: string) {
  const { setNodes } = useReactFlow();
  return useCallback(
    (patch: Partial<T>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === id ? { ...n, data: { ...(n.data as object), ...patch } } : n,
        ),
      );
    },
    [id, setNodes],
  );
}

function AssetNode({ id, data }: NodeProps<AssetData>) {
  const update = useUpdateNodeData<AssetData>(id);
  return (
    <div className="rf-node asset">
      <div className="rf-node-title">Asset</div>
      <label className="rf-field">
        <span>Ticker</span>
        <input
          className="nodrag"
          value={data.ticker}
          onChange={(e) => update({ ticker: e.target.value.toUpperCase() })}
        />
      </label>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function QuantNode({ id, data }: NodeProps<QuantData>) {
  const update = useUpdateNodeData<QuantData>(id);
  const catalog = useContext(CatalogContext);
  return (
    <div className="rf-node quant">
      <Handle type="target" position={Position.Left} />
      <div className="rf-node-title">Quant condition</div>
      <label className="rf-field">
        <span>Indicator</span>
        <select
          className="nodrag"
          value={data.indicator}
          onChange={(e) => update({ indicator: e.target.value })}
        >
          {(catalog?.indicators ?? []).map((i) => (
            <option key={i.key} value={i.key}>
              {i.label}
            </option>
          ))}
        </select>
      </label>
      <label className="rf-field">
        <span>Operator</span>
        <select
          className="nodrag"
          value={data.operator}
          onChange={(e) => update({ operator: e.target.value })}
        >
          {(catalog?.operators ?? []).map((o) => (
            <option key={o.key} value={o.key}>
              {o.key}
            </option>
          ))}
        </select>
      </label>
      <label className="rf-field">
        <span>Value</span>
        <input
          className="nodrag"
          type="number"
          step="any"
          value={data.value}
          onChange={(e) => update({ value: e.target.value })}
        />
      </label>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function AiNode({ id, data }: NodeProps<AiData>) {
  const update = useUpdateNodeData<AiData>(id);
  return (
    <div className="rf-node ai">
      <Handle type="target" position={Position.Left} />
      <div className="rf-node-title">AI confirmation</div>
      <label className="rf-field">
        <span>Prompt</span>
        <textarea
          className="nodrag"
          rows={3}
          value={data.prompt}
          onChange={(e) => update({ prompt: e.target.value })}
        />
      </label>
    </div>
  );
}

const nodeTypes: NodeTypes = { asset: AssetNode, quant: QuantNode, ai: AiNode };

function BuilderCanvas({ onCreated }: StrategyGraphBuilderProps) {
  const [nodes, setNodes] = useState<Node[]>(INITIAL_NODES);
  const [edges, setEdges] = useState<Edge[]>(INITIAL_EDGES);
  const [name, setName] = useState("Graph strategy");
  const [catalog, setCatalog] = useState<IndicatorCatalog | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get<IndicatorCatalog>("/indicators/");
        setCatalog(res.data);
      } catch (err) {
        setError(extractError(err));
      }
    })();
  }, []);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    [],
  );
  const onConnect = useCallback(
    (conn: Connection) => setEdges((eds) => addEdge(conn, eds)),
    [],
  );

  const onDeploy = async () => {
    setError(null);
    setSuccess(null);
    setDeploying(true);
    try {
      const payload = {
        name: name.trim() || "Graph strategy",
        nodes: nodes.map((n) => {
          if (n.type === "quant") {
            const d = n.data as QuantData;
            return {
              id: n.id,
              type: n.type,
              data: {
                indicator: d.indicator,
                operator: d.operator,
                value: Number(d.value),
                params: d.params ?? {},
              },
            };
          }
          return { id: n.id, type: n.type, data: n.data };
        }),
        edges: edges.map((e) => ({ source: e.source, target: e.target })),
      };
      const res = await api.post("/strategies/deploy-graph/", payload);
      setSuccess(`Deployed strategy: ${res.data?.name ?? "created"}.`);
      onCreated();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setDeploying(false);
    }
  };

  return (
    <CatalogContext.Provider value={catalog}>
      <div className="row gap wrap builder-toolbar">
        <input
          className="grow"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Strategy name"
          aria-label="Graph strategy name"
        />
        <button className="btn primary" onClick={() => void onDeploy()} disabled={deploying}>
          {deploying ? "Deploying…" : "Deploy graph"}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      <p className="muted small">
        Drag nodes to arrange. Connect Asset → Quant → AI by dragging between the handles.
        Inputs write straight back into each node.
      </p>

      <div className="rf-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </CatalogContext.Provider>
  );
}

export default function StrategyGraphBuilder({ onCreated }: StrategyGraphBuilderProps) {
  return (
    <ReactFlowProvider>
      <BuilderCanvas onCreated={onCreated} />
    </ReactFlowProvider>
  );
}
