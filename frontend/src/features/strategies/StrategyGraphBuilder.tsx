import { createContext, useCallback, useContext, useRef, useState } from "react";
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
import { extractError } from "../../api/errors";
import { useDeployGraph } from "./hooks";
import { useIndicatorCatalog } from "../../api/catalog";
import type { IndicatorCatalog } from "../../contract/types";
import CostEstimate, { useAtStrategyCap } from "./CostEstimate";
import {
  DEFAULT_DELIVERY,
  DeliveryChecks,
  DeliveryFields,
  toDeliveryPayload,
} from "./DeliverySettings";

type RightMode = "value" | "indicator";

interface AssetData {
  ticker: string;
}
interface QuantData {
  indicator: string;
  operator: string;
  value: string;
  params: Record<string, unknown>;
  rightMode: RightMode;
  rightIndicator: string;
  rightParam: string;
}
interface LogicData {
  op: "AND" | "OR";
}
interface AiData {
  prompt: string;
}

const CatalogContext = createContext<IndicatorCatalog | null>(null);

const INITIAL_NODES: Node[] = [
  { id: "asset-1", type: "asset", position: { x: 0, y: 120 }, data: { ticker: "AAPL" } },
  {
    id: "quant-1",
    type: "quant",
    position: { x: 260, y: 20 },
    data: {
      indicator: "RSI",
      operator: "<",
      value: "30",
      params: {},
      rightMode: "value",
      rightIndicator: "SMA",
      rightParam: "50",
    },
  },
  { id: "ai-1", type: "ai", position: { x: 720, y: 120 }, data: { prompt: "Confirm this is a genuine entry, not a falling knife." } },
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
  const indicators = catalog?.indicators ?? [];
  const rightSpec = indicators.find((i) => i.key === data.rightIndicator);
  const rightParamKey = Object.keys(rightSpec?.defaults ?? {})[0];
  return (
    <div className="rf-node quant">
      <Handle type="target" position={Position.Left} />
      <div className="rf-node-title">Quant condition</div>
      <label className="rf-field">
        <span>Indicator</span>
        <select className="nodrag" value={data.indicator} onChange={(e) => update({ indicator: e.target.value })}>
          {indicators.map((i) => (
            <option key={i.key} value={i.key}>{i.label}</option>
          ))}
        </select>
      </label>
      <label className="rf-field">
        <span>Operator</span>
        <select className="nodrag" value={data.operator} onChange={(e) => update({ operator: e.target.value })}>
          {(catalog?.operators ?? []).map((o) => (
            <option key={o.key} value={o.key}>{o.key}</option>
          ))}
        </select>
      </label>
      <label className="rf-field">
        <span>Compare against</span>
        <select
          className="nodrag"
          value={data.rightMode}
          onChange={(e) => update({ rightMode: e.target.value as RightMode })}
        >
          <option value="value">a constant</option>
          <option value="indicator">another indicator</option>
        </select>
      </label>
      {data.rightMode === "value" ? (
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
      ) : (
        <>
          <label className="rf-field">
            <span>Indicator</span>
            <select
              className="nodrag"
              value={data.rightIndicator}
              onChange={(e) => update({ rightIndicator: e.target.value })}
            >
              {indicators.map((i) => (
                <option key={i.key} value={i.key}>{i.label}</option>
              ))}
            </select>
          </label>
          {rightParamKey && (
            <label className="rf-field">
              <span>{rightParamKey}</span>
              <input
                className="nodrag"
                type="number"
                min={1}
                value={data.rightParam}
                onChange={(e) => update({ rightParam: e.target.value })}
              />
            </label>
          )}
        </>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function LogicNode({ id, data }: NodeProps<LogicData>) {
  const update = useUpdateNodeData<LogicData>(id);
  return (
    <div className="rf-node logic">
      <Handle type="target" position={Position.Left} />
      <div className="rf-node-title">Logic</div>
      <label className="rf-field">
        <span>Combine inputs with</span>
        <select className="nodrag" value={data.op} onChange={(e) => update({ op: e.target.value as "AND" | "OR" })}>
          <option value="AND">AND (all must hold)</option>
          <option value="OR">OR (any may hold)</option>
        </select>
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

const nodeTypes: NodeTypes = { asset: AssetNode, quant: QuantNode, logic: LogicNode, ai: AiNode };

function BuilderCanvas() {
  const [nodes, setNodes] = useState<Node[]>(INITIAL_NODES);
  const [edges, setEdges] = useState<Edge[]>(INITIAL_EDGES);
  const [name, setName] = useState("Graph strategy");
  // Shared session-cached catalog — deduped with StrategyForm's consumer.
  const catalogQuery = useIndicatorCatalog();
  const catalog = catalogQuery.data ?? null;
  const deploy = useDeployGraph();
  const atCap = useAtStrategyCap();
  const [error, setError] = useState<string | null>(null);
  const counter = useRef(2);

  // Delivery/scheduling settings — the same knobs (and defaults) as the plain form.
  const [delivery, setDelivery] = useState(DEFAULT_DELIVERY);

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

  const addQuant = () => {
    counter.current += 1;
    const id = `quant-${counter.current}`;
    setNodes((nds) => [
      ...nds,
      {
        id,
        type: "quant",
        position: { x: 260, y: 260 + counter.current * 10 },
        data: {
          indicator: "PRICE", operator: "cross_above", value: "0", params: {},
          rightMode: "indicator", rightIndicator: "SMA", rightParam: "50",
        },
      },
    ]);
  };

  const addLogic = () => {
    counter.current += 1;
    const id = `logic-${counter.current}`;
    setNodes((nds) => [
      ...nds,
      { id, type: "logic", position: { x: 500, y: 120 }, data: { op: "AND" } },
    ]);
  };

  const onDeploy = () => {
    setError(null);
    const wire = toDeliveryPayload(delivery);
    if (!wire.ok) {
      setError(wire.error);
      return;
    }
    deploy.mutate(
      {
        name: name.trim() || "Graph strategy",
        nodes: nodes.map((n) => {
          if (n.type === "quant") {
            const d = n.data as QuantData;
            const right =
              d.rightMode === "indicator"
                ? { right: { indicator: d.rightIndicator, params: rightParams(catalog, d) } }
                : { value: Number(d.value) };
            return {
              id: n.id,
              type: n.type,
              data: { indicator: d.indicator, operator: d.operator, params: d.params ?? {}, ...right },
            };
          }
          if (n.type === "logic") {
            return { id: n.id, type: n.type, data: { op: (n.data as LogicData).op } };
          }
          return { id: n.id, type: n.type, data: n.data as unknown };
        }),
        edges: edges.map((e) => ({ source: e.source, target: e.target })),
        ...wire.payload,
      },
      { onError: (err) => setError(extractError(err)) },
    );
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
        <button className="btn ghost" onClick={addQuant} type="button">+ Condition</button>
        <button className="btn ghost" onClick={addLogic} type="button">+ AND/OR</button>
        <button
          className="btn primary"
          onClick={onDeploy}
          disabled={deploy.isPending || atCap}
          title={atCap ? "This workspace is at its strategy cap — delete one to add another" : undefined}
        >
          {deploy.isPending ? "Deploying…" : atCap ? "Workspace at cap" : "Deploy graph"}
        </button>
      </div>

      <div className="form-grid builder-toolbar">
        <DeliveryFields value={delivery} onChange={setDelivery} />
      </div>
      <div className="builder-toolbar">
        <DeliveryChecks value={delivery} onChange={setDelivery} />
      </div>
      {/* The AI node on the canvas is what turns AI on for a graph strategy. */}
      <CostEstimate delivery={delivery} aiEnabled={nodes.some((n) => n.type === "ai")} />

      {catalogQuery.isError && (
        <div className="alert error">
          Could not load indicators: {extractError(catalogQuery.error)}
        </div>
      )}
      {error && <div className="alert error">{error}</div>}
      {deploy.isSuccess && (
        <div className="alert success">Deployed strategy: {deploy.data.name}.</div>
      )}

      <p className="muted small">
        Connect Asset → Condition(s) → AI. To combine conditions, drop an AND/OR node and wire
        each condition into it, then the AND/OR node into the AI node. A condition can compare an
        indicator to a constant or to another indicator (e.g. price crosses above its SMA).
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

function rightParams(catalog: IndicatorCatalog | null, d: QuantData): Record<string, number> {
  const spec = catalog?.indicators.find((i) => i.key === d.rightIndicator);
  const key = Object.keys(spec?.defaults ?? {})[0];
  if (!key || !d.rightParam) return {};
  return { [key]: Number(d.rightParam) };
}

export default function StrategyGraphBuilder() {
  return (
    <ReactFlowProvider>
      <BuilderCanvas />
    </ReactFlowProvider>
  );
}
