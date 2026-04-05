import toast from "react-hot-toast";
import { useScopeStore } from "../../store/scope-store";
import { router } from "../../router";

type EventMeta = {
  symbol?: string;
};

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function pickTradeId(payload: Record<string, unknown>): string {
  const candidate = [
    payload.order_id,
    payload.close_order_id,
    payload.client_order_id,
    payload.trade_id,
    payload.id,
  ].map(asString).find(Boolean);
  return candidate || "";
}

function buildLabel(eventName: string): string {
  if (eventName === "bot:position_opened") return "Position Opened";
  if (eventName === "bot:position_closed") return "Position Closed";
  return "Trade Filled";
}

export function showTradeEventToast(params: {
  eventName: string;
  data: unknown;
  meta?: EventMeta;
  dedupeKey: string;
}): void {
  const payload = asObject(params.data);
  const symbol = asString(payload.symbol) || asString(params.meta?.symbol) || "Unknown";
  const side = asString(payload.side || payload.direction || payload.action).toUpperCase();
  const size = asNumber(payload.size ?? payload.filled_size ?? payload.quantity ?? payload.qty);
  const pnl = asNumber(payload.net_pnl ?? payload.realized_pnl ?? payload.pnl);
  const exitReason = asString(
    payload.exit_reason || payload.exitReason || payload.close_reason || payload.closed_by || payload.reason
  );
  const tradeId = pickTradeId(payload);

  const sidePart = side ? ` ${side}` : "";
  const sizePart = size !== null ? ` · size ${size}` : "";
  const pnlPart = pnl !== null ? ` · PnL ${pnl.toFixed(2)}` : "";
  const reasonPart = exitReason ? ` · ${exitReason}` : "";
  const title = buildLabel(params.eventName);

  toast.custom(
    (t) => (
      <button
        type="button"
        onClick={() => {
          toast.dismiss(t.id);
          if (!tradeId) return;
          const scope = useScopeStore.getState();
          const targetParams = new URLSearchParams();
          targetParams.set("openTradeId", tradeId);
          if (scope.exchangeAccountId) targetParams.set("exchangeAccountId", scope.exchangeAccountId);
          if (scope.botId) targetParams.set("botId", scope.botId);
          if (scope.environment && scope.environment !== "all") {
            targetParams.set("environment", scope.environment);
          }
          const target = `/trade-history?${targetParams.toString()}`;
          router.navigate(target);
        }}
        className="w-[360px] rounded-lg border border-border bg-background px-4 py-3 text-left shadow-lg hover:bg-accent/40"
      >
        <div className="text-sm font-semibold">{title}</div>
        <div className="mt-1 text-sm text-muted-foreground">
          {symbol}
          {sidePart}
          {sizePart}
          {pnlPart}
          {reasonPart}
        </div>
        <div className="mt-2 text-xs text-primary">
          {tradeId ? "Click to open trade details" : "Trade ID unavailable"}
        </div>
      </button>
    ),
    { id: params.dedupeKey, duration: 10000 }
  );
}
