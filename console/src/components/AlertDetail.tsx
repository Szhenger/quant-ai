import type { Alert } from "../api/types";

/**
 * "Why did this fire, and where did it go?" — renders the alert's persisted
 * audit trail: the evaluated condition tree (every leaf with the concrete
 * operand values that produced it) and the per-channel delivery outcomes.
 */

interface DetailOperand {
  indicator?: string;
  params?: Record<string, unknown>;
  value?: number | null;
  previous?: number | null;
}

interface DetailCompare {
  type: "compare";
  operator: string;
  result: boolean;
  left: DetailOperand;
  right: DetailOperand;
}

interface DetailGroup {
  type: "group";
  op: string;
  result: boolean;
  children: DetailNode[];
}

type DetailNode = DetailCompare | DetailGroup;

function isDetailNode(x: unknown): x is DetailNode {
  return (
    typeof x === "object" &&
    x !== null &&
    ((x as { type?: unknown }).type === "compare" || (x as { type?: unknown }).type === "group")
  );
}

function fmt(v: number | null | undefined): string {
  return typeof v === "number" ? v.toFixed(4) : "—";
}

function operandLabel(o: DetailOperand): string {
  if (o.indicator) {
    const params = o.params && Object.keys(o.params).length > 0
      ? `(${Object.entries(o.params).map(([k, v]) => `${k}=${String(v)}`).join(",")})`
      : "";
    return `${o.indicator}${params}`;
  }
  return "const";
}

function ConditionNode({ node, depth }: { node: DetailNode; depth: number }) {
  const mark = node.result ? "✓" : "✗";
  const markClass = node.result ? "detail-hit" : "detail-miss";
  if (node.type === "group") {
    return (
      <div className="detail-node" style={{ marginLeft: depth * 16 }}>
        <span className={markClass}>{mark}</span>{" "}
        <span className="mono">{node.op}</span>
        {node.children.filter(isDetailNode).map((c, i) => (
          <ConditionNode key={i} node={c} depth={depth + 1} />
        ))}
      </div>
    );
  }
  return (
    <div className="detail-node" style={{ marginLeft: depth * 16 }}>
      <span className={markClass}>{mark}</span>{" "}
      <span className="mono">
        {operandLabel(node.left)} {node.operator} {operandLabel(node.right)}
      </span>{" "}
      <span className="muted small">
        {fmt(node.left.value)} vs {fmt(node.right.value)}
        {node.operator.startsWith("cross_") && (
          <> (prev {fmt(node.left.previous)} vs {fmt(node.right.previous)})</>
        )}
      </span>
    </div>
  );
}

interface ChannelOutcome {
  ok?: boolean;
  detail?: string;
  attempts?: number;
  permanent?: boolean;
}

export default function AlertDetail({ alert }: { alert: Alert }) {
  const tree = isDetailNode(alert.condition_detail) ? alert.condition_detail : null;
  const delivery =
    alert.delivery && typeof alert.delivery === "object"
      ? (alert.delivery as Record<string, ChannelOutcome>)
      : {};
  const channels = Object.entries(delivery);

  return (
    <div className="alert-detail">
      <div className="detail-section">
        <span className="muted small">Condition at fire time</span>
        {tree ? (
          <ConditionNode node={tree} depth={0} />
        ) : (
          <p className="muted small">No condition audit recorded for this alert.</p>
        )}
      </div>

      <div className="detail-section">
        <span className="muted small">Delivery</span>
        {channels.length === 0 ? (
          <p className="muted small">No delivery channels were enabled.</p>
        ) : (
          <ul className="detail-delivery">
            {channels.map(([channel, outcome]) => (
              <li key={channel}>
                <span className={outcome.ok ? "detail-hit" : "detail-miss"}>
                  {outcome.ok ? "✓" : "✗"}
                </span>{" "}
                <span className="mono">{channel}</span>
                <span className="muted small">
                  {outcome.attempts != null && ` · ${outcome.attempts} attempt${outcome.attempts === 1 ? "" : "s"}`}
                  {outcome.detail && ` · ${outcome.detail}`}
                  {outcome.ok === false && outcome.permanent && " · won't retry"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
