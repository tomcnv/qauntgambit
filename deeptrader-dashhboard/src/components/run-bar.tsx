/**
 * RunBar - Sticky control bar for Trading section
 * 
 * Shows at a glance:
 * - What am I scoped to? (Exchange account / environment)
 * - What is currently active? (Active bot + version)
 * - Is it healthy + processing? (Status, heartbeat, last decision, latency)
 * - Can I start/pause/kill safely? (Controls)
 */

import { useState, useMemo, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import {
  Play,
  Pause,
  Activity,
  Clock,
  Zap,
  Timer,
  CheckCircle2,
  Bot,
  Settings,
  ChevronRight,
  ChevronDown,
  Info,
  Shield,
  Target,
  Wallet,
  TrendingUp,
  TrendingDown,
  DollarSign,
  AlertTriangle,
  Square,
  XCircle,
  Layers,
} from "lucide-react";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import { cn } from "../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "./ui/tooltip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./ui/alert-dialog";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { Separator } from "./ui/separator";
import { useScopeStore } from "../store/scope-store";
import useAuthStore from "../store/auth-store";
import { useExchangeAccounts } from "../lib/api/exchange-accounts-hooks";
import { useBotInstances, useOverviewData, useWarmupStatus, useHealthSnapshot, useControlStatus } from "../lib/api/hooks";
import { useWebSocketContext } from "../lib/websocket/WebSocketProvider";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { startBotById, stopBotById, fetchCommandResults } from "../lib/api/control";
import {
  fetchRuntimeConfigEffective,
  fetchRuntimeKnobs,
  applyRuntimeConfig,
  closeAllPositions,
  cancelAllOrders,
  type RuntimeKnobSpec,
} from "../lib/api/client";
import { triggerKillSwitch } from "../lib/api/quant-hooks";
import toast from "react-hot-toast";
import { ExchangeLogo } from "./scope-selector";
import { BotStartupModal, useBotStartupModal } from "./BotStartupModal";

const KNOB_KEY_ALIASES: Record<string, string[]> = {
  risk_per_trade_pct: ["risk_per_trade_pct", "riskPerTradePct", "positionSizePct"],
  max_total_exposure_pct: ["max_total_exposure_pct", "maxTotalExposurePct"],
  max_exposure_per_symbol_pct: ["max_exposure_per_symbol_pct", "maxExposurePerSymbolPct"],
  max_positions: ["max_positions", "maxPositions"],
  max_positions_per_symbol: ["max_positions_per_symbol", "maxPositionsPerSymbol"],
  max_daily_drawdown_pct: ["max_daily_drawdown_pct", "maxDailyDrawdownPct", "maxDailyLossPct"],
  max_drawdown_pct: ["max_drawdown_pct", "maxDrawdownPct"],
  max_leverage: ["max_leverage", "maxLeverage"],
  min_order_interval_sec: ["min_order_interval_sec", "minOrderIntervalSec", "minTradeIntervalSec"],
  max_retries: ["max_retries", "maxRetries"],
  retry_delay_sec: ["retry_delay_sec", "retryDelaySec"],
  execution_timeout_sec: ["execution_timeout_sec", "executionTimeoutSec"],
  max_slippage_bps: ["max_slippage_bps", "maxSlippageBps"],
  default_stop_loss_pct: ["default_stop_loss_pct", "defaultStopLossPct", "stopLossPct"],
  default_take_profit_pct: ["default_take_profit_pct", "defaultTakeProfitPct", "takeProfitPct"],
  order_intent_max_age_sec: ["order_intent_max_age_sec", "orderIntentMaxAgeSec"],
  position_continuation_gate_enabled: ["position_continuation_gate_enabled"],
  enable_unified_confirmation_policy: ["enable_unified_confirmation_policy"],
  prediction_score_gate_enabled: ["prediction_score_gate_enabled"],
};

function getKnobAliases(key: string): string[] {
  return KNOB_KEY_ALIASES[key] || [key];
}

function readKnobValue(sectionValues: Record<string, any>, key: string): any {
  for (const alias of getKnobAliases(key)) {
    if (Object.prototype.hasOwnProperty.call(sectionValues, alias)) {
      return sectionValues[alias];
    }
  }
  return undefined;
}

function resolveWriteKey(sectionValues: Record<string, any>, key: string): string {
  for (const alias of getKnobAliases(key)) {
    if (Object.prototype.hasOwnProperty.call(sectionValues, alias)) {
      return alias;
    }
  }
  return key;
}

function validateRuntimeConfig(knobs: RuntimeKnobSpec[], cfg: Record<string, unknown> | null): string[] {
  if (!cfg) return ["Config not loaded"];
  const config = cfg as Record<string, any>;
  const errors: string[] = [];
  for (const knob of knobs) {
    const sectionValues = (config[knob.section] || {}) as Record<string, any>;
    let value = readKnobValue(sectionValues, knob.key);
    if (value === undefined || value === null || value === "") value = knob.default;
    if (value === undefined || value === null || value === "") continue;
    if (knob.type === "int" || knob.type === "float") {
      const num = Number(value);
      if (!Number.isFinite(num)) {
        errors.push(`${knob.label}: must be a valid number`);
        continue;
      }
      if (knob.min != null && num < knob.min) errors.push(`${knob.label}: must be >= ${knob.min}`);
      if (knob.max != null && num > knob.max) errors.push(`${knob.label}: must be <= ${knob.max}`);
    }
  }
  const risk = (config.risk_config || {}) as Record<string, any>;
  const execution = (config.execution_config || {}) as Record<string, any>;
  const maxPos = Number(readKnobValue(risk, "max_positions") ?? 0);
  const maxPosSym = Number(readKnobValue(risk, "max_positions_per_symbol") ?? 0);
  if (Number.isFinite(maxPos) && Number.isFinite(maxPosSym) && maxPos > 0 && maxPosSym > maxPos) {
    errors.push("Max Positions Per Symbol cannot exceed Max Positions");
  }
  const maxTotalExposure = Number(readKnobValue(risk, "max_total_exposure_pct") ?? 0);
  const maxSymExposure = Number(readKnobValue(risk, "max_exposure_per_symbol_pct") ?? 0);
  if (
    Number.isFinite(maxTotalExposure) &&
    Number.isFinite(maxSymExposure) &&
    maxTotalExposure > 0 &&
    maxSymExposure > maxTotalExposure
  ) {
    errors.push("Max Exposure Per Symbol % cannot exceed Max Total Exposure %");
  }
  const sl = Number(readKnobValue(execution, "default_stop_loss_pct"));
  const tp = Number(readKnobValue(execution, "default_take_profit_pct"));
  if (Number.isFinite(sl) && Number.isFinite(tp) && tp < sl) {
    errors.push("Take Profit % should be greater than or equal to Stop Loss %");
  }
  return errors;
}

function collectFieldErrors(knobs: RuntimeKnobSpec[], cfg: Record<string, unknown> | null): Record<string, string> {
  if (!cfg) return {};
  const config = cfg as Record<string, any>;
  const fieldErrors: Record<string, string> = {};
  for (const knob of knobs) {
    const sectionValues = (config[knob.section] || {}) as Record<string, any>;
    let value = readKnobValue(sectionValues, knob.key);
    if (value === undefined || value === null || value === "") value = knob.default;
    if (value === undefined || value === null || value === "") continue;
    if (knob.type !== "int" && knob.type !== "float") continue;
    const num = Number(value);
    const id = `${knob.section}.${knob.key}`;
    if (!Number.isFinite(num)) {
      fieldErrors[id] = "Must be a valid number";
      continue;
    }
    if (knob.min != null && num < knob.min) {
      fieldErrors[id] = `Must be >= ${knob.min}`;
      continue;
    }
    if (knob.max != null && num > knob.max) {
      fieldErrors[id] = `Must be <= ${knob.max}`;
    }
  }
  return fieldErrors;
}

function formatApiError(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) return detail.map((x) => String(x)).join(", ");
  if (detail && typeof detail === "object") {
    if (Array.isArray((detail as any).validation_errors) && (detail as any).validation_errors.length > 0) {
      return (detail as any).validation_errors.join(", ");
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  const msg = err?.message;
  if (typeof msg === "string" && msg.trim()) return msg;
  return fallback;
}

function formatDurationShort(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60}m`;
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remSeconds = seconds % 60;
    return remSeconds > 0 ? `${minutes}m ${remSeconds}s` : `${minutes}m`;
  }
  return `${seconds}s`;
}

// ============================================================================
// TYPES
// ============================================================================

interface RunBarProps {
  /** Show full controls or just compact status or minimal link */
  variant?: "full" | "compact" | "minimal";
}

// ============================================================================
// HELPER COMPONENTS
// ============================================================================

function StatusPill({ 
  status, 
  label, 
  tooltip,
  pulse = false 
}: { 
  status: "success" | "warning" | "error" | "neutral"; 
  label: string; 
  tooltip?: string;
  pulse?: boolean;
}) {
  const colors = {
    success: "bg-emerald-500",
    warning: "bg-amber-500",
    error: "bg-red-500",
    neutral: "bg-muted-foreground/50",
  };

  const content = (
    <div className="flex items-center gap-1.5 cursor-default">
      <span className={cn(
        "h-2 w-2 rounded-full",
        colors[status],
        pulse && "animate-pulse"
      )} />
      <span className={cn(
        "text-xs font-medium",
        status === "success" && "text-emerald-600 dark:text-emerald-400",
        status === "warning" && "text-amber-600 dark:text-amber-400",
        status === "error" && "text-red-600 dark:text-red-400",
        status === "neutral" && "text-muted-foreground"
      )}>
        {label}
      </span>
    </div>
  );

  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{content}</TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    );
  }

  return content;
}

function MetricChip({ 
  icon: Icon, 
  label, 
  value, 
  tooltip,
  status = "neutral"
}: { 
  icon: React.ElementType; 
  label: string; 
  value: string | number;
  tooltip?: string;
  status?: "success" | "warning" | "error" | "neutral";
}) {
  const content = (
    <div className={cn(
      "flex items-center gap-1.5 px-2 py-1 rounded-md bg-muted/50 text-xs",
      status === "warning" && "bg-amber-500/10 text-amber-600 dark:text-amber-400",
      status === "error" && "bg-red-500/10 text-red-600 dark:text-red-400"
    )}>
      <Icon className="h-3 w-3 text-muted-foreground" />
      <span className="text-muted-foreground hidden sm:inline">{label}:</span>
      <span className="font-mono font-medium">{value}</span>
    </div>
  );

  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="cursor-default">{content}</div>
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    );
  }

  return content;
}

// Enhanced warmup tooltip showing per-symbol AMT/HTF status
function WarmupTooltipContent({ warmupData }: { warmupData: any }) {
  if (!warmupData?.symbols) {
    return <span>Loading warmup data...</span>;
  }

  const symbols = Object.entries(warmupData.symbols);
  const reasonLabels: Record<string, string> = {
    warmup: "Collecting samples",
    quality_missing: "Quality score missing",
    quality_low: "Quality score below threshold",
    data_stale: "Market data stale",
    orderbook_unsynced: "Orderbook not synced",
    trade_unsynced: "Trades not synced",
    candle_unsynced: "Candles not synced",
  };
  const formatReasons = (reasons?: string[]) =>
    (reasons || []).map((reason) => reasonLabels[reason] || reason);

  const getProgress = (entry: any) =>
    entry?.overallProgress ??
    entry?.progress ??
    entry?.amt?.progress ??
    0;
  const getReady = (entry: any) =>
    entry?.overallReady ?? entry?.ready ?? entry?.amt?.ready ?? false;
  const getSampleCount = (entry: any) =>
    entry?.sampleCount ?? entry?.amt?.sampleCount ?? 0;
  const getMinSamples = (entry: any) =>
    entry?.minSamples ?? entry?.amt?.minSamples ?? 0;
  const getCandleCount = (entry: any) =>
    entry?.candleCount ?? entry?.amt?.candleCount ?? 0;
  const getMinCandles = (entry: any) =>
    entry?.minCandles ?? entry?.amt?.minCandles ?? 0;

  return (
    <div className="space-y-3 min-w-[280px]">
      <div className="font-semibold text-sm border-b pb-2 flex items-center justify-between">
        <span>Data Warmup Progress</span>
        <span className="text-muted-foreground font-normal">
          {Math.round(warmupData.overall?.progress || 0)}%
        </span>
      </div>

      {symbols.map(([symbol, data]: [string, any]) => {
        const progress = getProgress(data);
        const ready = getReady(data);
        const sampleCount = getSampleCount(data);
        const minSamples = getMinSamples(data);
        const candleCount = getCandleCount(data);
        const minCandles = getMinCandles(data);
        return (
          <div key={symbol} className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-medium">{symbol}</span>
              <span className={cn(
                "text-[10px] px-1.5 py-0.5 rounded",
                ready
                  ? "bg-emerald-500/20 text-emerald-600"
                  : "bg-amber-500/20 text-amber-600"
              )}>
                {ready ? "READY" : `${Math.round(progress || 0)}%`}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="flex items-center gap-1.5">
                <span className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  ready ? "bg-emerald-500" : "bg-amber-500 animate-pulse"
                )} />
                <span className="text-muted-foreground">Samples:</span>
                <span className={cn(
                  "font-medium",
                  ready ? "text-emerald-600" : "text-amber-600"
                )}>
                  {sampleCount}/{minSamples || "?"}
                </span>
              </div>

              <div className="flex items-center gap-1.5">
                <span className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  ready ? "bg-emerald-500" : "bg-amber-500 animate-pulse"
                )} />
                <span className="text-muted-foreground">Candles:</span>
                <span className={cn(
                  "font-medium",
                  ready ? "text-emerald-600" : "text-amber-600"
                )}>
                  {candleCount}/{minCandles || "?"}
                </span>
              </div>
            </div>
            {!ready && data.reasons?.length > 0 && (
              <div className="text-[10px] text-muted-foreground">
                <span className="font-medium text-foreground">Reasons:</span>{" "}
                {formatReasons(data.reasons).join(", ")}
              </div>
            )}
          </div>
        );
      })}

      <div className="pt-2 border-t text-[10px] text-muted-foreground">
        <div><strong>Samples</strong> = market snapshots collected</div>
        <div><strong>Candles</strong> = HTF data accumulation</div>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function RunBar({ variant = "full" }: RunBarProps) {
  const queryClient = useQueryClient();
  const [configSheetOpen, setConfigSheetOpen] = useState(false);
  const [runtimeConfigOpen, setRuntimeConfigOpen] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, unknown> | null>(null);
  const [runtimeKnobs, setRuntimeKnobs] = useState<RuntimeKnobSpec[]>([]);
  const [runtimeEnabledSymbols, setRuntimeEnabledSymbols] = useState<string>("");
  const [runtimeConfigVersion, setRuntimeConfigVersion] = useState<number | null>(null);
  const [runtimeConfigLoading, setRuntimeConfigLoading] = useState(false);
  const [runtimeConfigSaving, setRuntimeConfigSaving] = useState(false);
  const [runtimeConfigError, setRuntimeConfigError] = useState<string | null>(null);
  const [startupWarning, setStartupWarning] = useState<string | null>(null);
  const [warmupLock, setWarmupLock] = useState(false);
  
  // Bot startup modal
  const startupModal = useBotStartupModal();
  const [queuedCommandId, setQueuedCommandId] = useState<string | null>(null);
  
  // Scope state
  const { 
    level: scopeLevel, 
    exchangeAccountId, 
    exchangeAccountName, 
    botId,
    botName: scopeBotName,
  } = useScopeStore();
  const authUser = useAuthStore((state) => state.user);
  const authToken = useAuthStore((state) => state.token);
  
  // Data fetching - initial (no bot ID dependency)
  const { data: exchangeAccounts = [] } = useExchangeAccounts();
  const { data: botInstancesData } = useBotInstances();
  
  const allBots = (botInstancesData as any)?.bots || [];
  
  // Find bot for selected exchange
  const botForExchange = allBots.find((bot: any) => 
    bot.exchangeConfigs?.some((config: any) => config.exchange_account_id === exchangeAccountId)
  );
  
  // Resolve run-bar strictly from the currently selected scope.
  const runBarBotId =
    scopeLevel === "bot" ? botId || null :
    scopeLevel === "exchange" ? botForExchange?.id || null :
    null;
  const runBarExchangeAccountId =
    scopeLevel === "fleet" ? null :
    exchangeAccountId || botForExchange?.exchangeConfigs?.[0]?.exchange_account_id || null;
  const runBarConfigForExchange =
    runBarBotId && runBarExchangeAccountId
      ? (allBots.find((bot: any) => bot.id === runBarBotId)?.exchangeConfigs?.find(
          (config: any) => config.exchange_account_id === runBarExchangeAccountId,
        ) || null)
      : null;
  const runBarBotExchangeConfigId =
    runBarConfigForExchange?.id ||
    (scopeLevel === "exchange" ? botForExchange?.exchangeConfigs?.[0]?.id : null) ||
    null;

  // Data fetching that depends on the selected scoped bot/account
  const { data: overviewData, isLoading: overviewLoading } = useOverviewData({
    botId: runBarBotId || undefined,
    exchangeAccountId: runBarExchangeAccountId || undefined,
  });
  const tenantIdEnv = import.meta.env.VITE_TENANT_ID as string | undefined;
  const tenantId = useMemo(() => {
    // Always prefer the authenticated session over static env fallbacks.
    if (authUser?.id) return authUser.id;
    // Fallback: try to decode access token for tenant_id claim
    const token = authToken;
    if (token && token.split(".").length === 3) {
      try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        return payload.tenant_id || payload.tenantId;
      } catch {
        // ignore
      }
    }
    return tenantIdEnv;
  }, [authToken, authUser?.id, tenantIdEnv]);

  const { data: warmupData } = useWarmupStatus(runBarBotId, tenantId);
  const { data: controlStatus } = useControlStatus(runBarBotId, tenantId);
  const { data: healthData } = useHealthSnapshot({ botId: runBarBotId || undefined, tenantId });
  const { isConnected: wsConnected } = useWebSocketContext();
  const startLocked = controlStatus?.startLock?.locked ?? false;
  const runtimeFieldErrors = useMemo(
    () => collectFieldErrors(runtimeKnobs, runtimeConfig),
    [runtimeKnobs, runtimeConfig],
  );
  const runtimeValidationErrors = useMemo(
    () => validateRuntimeConfig(runtimeKnobs, runtimeConfig),
    [runtimeKnobs, runtimeConfig],
  );

  // Load runtime config on demand
  useEffect(() => {
    const configId = runBarBotExchangeConfigId;
    if (!runtimeConfigOpen || !configId) return;
    let cancelled = false;
    setRuntimeConfigLoading(true);
    setRuntimeConfigError(null);
    Promise.all([fetchRuntimeConfigEffective(configId), fetchRuntimeKnobs()])
      .then(([effective, knobs]) => {
        if (cancelled) return;
        const cfg = effective?.config ?? null;
        setRuntimeConfig(cfg);
        setRuntimeConfigVersion(cfg?.config_version ?? null);
        setRuntimeEnabledSymbols((cfg?.enabled_symbols || []).join(", "));
        setRuntimeKnobs(knobs?.knobs || []);
      })
      .catch((err) => {
        if (cancelled) return;
        setRuntimeConfigError(err?.message || "Failed to load runtime config");
      })
      .finally(() => {
        if (!cancelled) setRuntimeConfigLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runtimeConfigOpen, runBarBotExchangeConfigId]);
  
  // Selected account details
  const selectedAccount = (exchangeAccounts as any[]).find(
    (acc: any) => acc.id === exchangeAccountId
  );
  
  // Parse exchange info
  const getExchangeFromName = (name: string | null): string | null => {
    if (!name) return null;
    const match = name.match(/\(([^)]+)\)$/);
    return match ? match[1].toLowerCase() : null;
  };
  
  const exchange = selectedAccount?.venue || getExchangeFromName(exchangeAccountName);
  const accountLabel = exchangeAccountName?.replace(/\s*\([^)]+\)$/, '') || selectedAccount?.name || 'Select';
  const displayBotName = scopeBotName || botForExchange?.name || null;
  const configVersion = runBarConfigForExchange?.config_version || null;
  
  // Bot status
  const botStatus = overviewData?.botStatus as any;
  const fastScalper = overviewData?.fastScalper as any;
  const liveStatus = overviewData?.liveStatus as any;
  const tradingInfo = botStatus?.trading as any;
  // Metrics: prefer scopedMetrics from /api/dashboard/metrics (most accurate for balance/PnL)
  // fetchDashboardMetrics already unwraps res.data.data, so scopedMetrics IS the metrics object
  // Fall back to botStatus.metrics or fastScalper.metrics
  const scopedMetricsData = overviewData?.scopedMetrics as any;
  const metrics = scopedMetricsData ?? botStatus?.metrics ?? fastScalper?.metrics ?? {};
  const liveBotStatus = String(liveStatus?.botStatus || "").toLowerCase();
  const rawHealthStatus = String((healthData as any)?.status ?? "").toLowerCase();
  const rawPythonEngineStatus = String(
    (healthData as any)?.services?.python_engine?.status ??
    (healthData as any)?.serviceHealth?.services?.python_engine?.status ??
    ""
  ).toLowerCase();
  const explicitRuntimeStopped =
    rawHealthStatus === "stopped" || rawPythonEngineStatus === "stopped";
  const liveIsRunning = liveBotStatus === "running";
  const healthHeartbeatAlive = (healthData as any)?.botStatus?.heartbeatAlive === true;
  const controlTradingActive = controlStatus?.control?.trading_active === true;
  const controlTradingPaused = controlStatus?.control?.trading_paused === true;
  const platformStatus = liveStatus?.health?.status ?? botStatus?.platform?.status ?? fastScalper?.status ?? "offline";
  const runtimeHeartbeatActive =
    !explicitRuntimeStopped &&
    (
      healthHeartbeatAlive ||
      rawHealthStatus === "ok" ||
      rawPythonEngineStatus === "online" ||
      fastScalper?.status === "online"
    );
  const isTradingActive =
    !explicitRuntimeStopped &&
    (
      liveIsRunning ||
      (tradingInfo?.isActive ?? false) ||
      (controlTradingActive && !controlTradingPaused) ||
      healthHeartbeatAlive ||
      platformStatus === "running" ||
      fastScalper?.status === "running" ||
      fastScalper?.status === "online"
    );
  const runtimeActuallyActive = isTradingActive && runtimeHeartbeatActive;
  const environment = runBarConfigForExchange?.environment || 
    selectedAccount?.environment || 
    botForExchange?.exchangeConfigs?.[0]?.environment ||
    tradingInfo?.mode || 
    "paper";
  const tradingModeLabel = (environment || "paper").toUpperCase();
  
  // Trading blockers/throttles
  const tradingBlockers = botStatus?.tradingBlockers ?? [];
  const bladeSignals = botStatus?.bladeSignals ?? {};
  const hasBlockers = tradingBlockers.length > 0;
  const hasErrorBlocker = tradingBlockers.some((b: any) => b.severity === 'error');
  const hasWarningBlocker = tradingBlockers.some((b: any) => b.severity === 'warning');
  
  // Health metrics - use timestamp from bot status as heartbeat indicator
  const lastHeartbeatAgeSec = botStatus?.stats?.lastHeartbeatAge ?? null;
  const lastHeartbeat = botStatus?.timestamp ?? fastScalper?.timestamp ?? fastScalper?.lastHeartbeat ?? null;
  const lastDecision =
    botStatus?.stats?.lastDecision ??
    fastScalper?.lastDecision ??
    metrics?.lastDecision ??
    (lastHeartbeat ? { timestamp: lastHeartbeat } : null);
  const evalRate = metrics?.decisions_per_sec ?? metrics?.decisionsPerSec ?? 0;
  const p95Latency = metrics?.p95_latency ?? metrics?.p95Latency ?? 0;
  
  // Financial metrics - prioritize live data from API
  // API returns exchange_balance (USDT wallet balance) and _isPaper flag
  const apiExchangeBalance = metrics?.exchange_balance ?? metrics?.account_balance ?? metrics?.current_equity;
  const apiIsPaper = metrics?._isPaper;
  
  // Debug: log what we're getting
  if (typeof window !== 'undefined' && (window as any).__DEBUG_RUNBAR__) {
    console.log('[RunBar Debug]', {
      scopedMetricsData,
      metrics,
      apiExchangeBalance,
      apiIsPaper,
      runBarBotId,
      runBarExchangeAccountId,
    });
  }
  
  // Determine if this is a paper account:
  // 1. API explicitly says _isPaper: true
  // 2. No API data AND account environment is 'paper'
  const isPaperAccount = apiIsPaper === true || 
    (apiIsPaper === undefined && selectedAccount?.environment === 'paper');
  
  // Paper trading state
  const initialPaperCapital = selectedAccount?.metadata?.paperCapital ?? selectedAccount?.exchange_balance ?? 10000;
  const paperCurrentBalance = apiExchangeBalance ?? selectedAccount?.exchange_balance ?? initialPaperCapital;
  const paperTotalPnl = metrics?.total_pnl ?? metrics?.totalPnl ?? metrics?.daily_pnl ?? fastScalper?.metrics?.dailyPnl ?? 0;
  
  // Exchange balance: use API data when available, regardless of paper status
  // This ensures we show the real USDT balance from the exchange
  // If no data available, show null (not a fake default)
  const rawExchangeBalance = 
    apiExchangeBalance ?? // First: live API data (USDT wallet balance)
    (isPaperAccount ? paperCurrentBalance : null) ?? // Second: paper balance if paper mode
    selectedAccount?.exchange_balance ?? // Third: stored account balance
    null;
  const exchangeBalance = rawExchangeBalance !== null ? Number(rawExchangeBalance) : null;
  const tradingCapital = isPaperAccount
    ? initialPaperCapital
    : (metrics?.trading_capital ?? selectedAccount?.trading_capital ?? exchangeBalance ?? null);
  // Use total_pnl (realized + unrealized) for 24h P&L display - shows full P&L including open positions
  const dailyPnl = metrics?.total_pnl ?? metrics?.totalPnl ?? metrics?.daily_pnl ?? fastScalper?.metrics?.dailyPnl ?? 0;
  const dailyPnlPct = tradingCapital > 0 ? (dailyPnl / tradingCapital) * 100 : 0;
  
  // For paper accounts, also show cumulative P&L
  const cumulativePnl = isPaperAccount ? paperTotalPnl : 0;
  
  // Warmup status
  const symbolWarmupEntries = useMemo(
    () => Object.values((warmupData?.symbols || {}) as Record<string, any>),
    [warmupData?.symbols],
  );
  const inferredWarmupReady =
    symbolWarmupEntries.length > 0 &&
    symbolWarmupEntries.every((entry: any) => entry?.ready === true);
  const warmupReady = (warmupData?.overall?.ready ?? false) || inferredWarmupReady;
  const warmupProgress = warmupReady
    ? 100
    : (warmupData?.overall?.progress ?? 0);
  
  // Collect all reasons from symbols for tooltip display
  const warmupReasons = useMemo(() => {
    const symbols = warmupData?.symbols;
    if (!symbols) return [];
    const reasons = new Set<string>();
    Object.values(symbols).forEach((entry: any) => {
      (entry?.reasons || []).forEach((reason: string) => reasons.add(reason));
    });
    return Array.from(reasons);
  }, [warmupData]);
  
  // Critical data issues that would block trading AFTER warmup completes
  // These are issues that won't resolve just by waiting for more data
  const criticalDataIssues = useMemo(() => {
    const critical = new Set<string>();
    // Only TRUE feed failures should be critical - NOT transient staleness
    // 'data_stale' and 'stale_data' are often transient and can clear up
    // Only block on actual feed/connection failures
    const criticalReasons = ['feed_error', 'exchange_error', 'connection_lost', 'feed_down'];
    warmupReasons.forEach(reason => {
      if (criticalReasons.includes(reason)) critical.add(reason);
    });
    return Array.from(critical);
  }, [warmupReasons]);
  
  // Only show "data issues" if warmup is done but there are CRITICAL issues remaining
  const dataIssues = warmupReady && criticalDataIssues.length > 0;

  // Credentials
  const hasVerifiedCredential = selectedAccount?.status === 'verified';
  
  // Python workers status - prefer health snapshot; fall back to serviceHealth and fastScalper
  const services = (healthData as any)?.services ?? (healthData as any)?.serviceHealth?.services ?? (healthData as any)?.liveStatus?.health ?? null;
  const serviceHealth = (healthData as any)?.serviceHealth ?? (healthData as any)?.liveStatus ?? null;
  const hasHealthData = Boolean(serviceHealth || services);
  const pythonEngine =
    (healthData as any)?.services?.python_engine ??
    (healthData as any)?.serviceHealth?.python_engine ??
    (services as any)?.python_engine ??
    null;
  const controlManager = pythonEngine?.control ?? (services as any)?.control_manager ?? null;
  const workers = pythonEngine?.workers ?? (services as any)?.workers ?? {};
  
  // Check which workers are required and their status
  // Essential workers: control manager + data_worker (provides market data)
  // Consider service_health "all_ready" as a strong signal that infra is up
  const serviceHealthReady = serviceHealth?.all_ready === true || (Array.isArray(serviceHealth?.missing) && serviceHealth?.missing.length === 0);

  // When bot is not running yet, health data won't exist - allow start in that case
  // The control-manager PM2 process handles launching, not the Python runtime
  const noBotRunning = !fastScalper?.status || fastScalper?.status === 'unknown' || fastScalper?.status === 'offline';
  
  const dataWorkerRunning =
    noBotRunning || // Allow start when no bot is running (bootstrap case)
    workers.data_worker?.status === 'running' ||
    workers.data_worker === 'running' ||
    workers.data_worker === true ||
    pythonEngine?.status === 'online' ||
    fastScalper?.status === 'online' ||
    serviceHealthReady ||
    hasHealthData; // optimistic: if health exists at all, assume data worker is reachable
  const controlManagerRunning =
    noBotRunning || // Allow start when no bot is running (bootstrap case)
    controlManager?.status === 'running' ||
    controlManager === 'running' ||
    controlManager === true ||
    pythonEngine?.control?.fresh === true ||
    fastScalper?.status === 'online' ||
    serviceHealthReady ||
    hasHealthData; // optimistic for same reason
  
  // For the bot to start, relax gating to avoid deadlock on missing worker detail
  const essentialWorkersRunning = controlManagerRunning && dataWorkerRunning;
  const botRuntimeHealthy =
    (healthData as any)?.status === "ok" ||
    runtimeHeartbeatActive ||
    serviceHealthReady ||
    essentialWorkersRunning;

  // Keep the local warmup lock in sync with the control-manager lock from the backend.
  // Also clear stale warmup UI state after failed starts where the runtime never came up.
  useEffect(() => {
    if (startLocked) {
      setWarmupLock(true);
    } else if (warmupReady) {
      // Clear the local lock once backend lock is gone and warmup is done
      setWarmupLock(false);
    } else if (!runtimeHeartbeatActive && warmupProgress <= 0) {
      setWarmupLock(false);
    }
  }, [startLocked, warmupReady, runtimeHeartbeatActive, warmupProgress]);
  
  // Build list of issues for tooltip
  const workerIssues: string[] = [];
  if (!hasHealthData) {
    workerIssues.push("Health data unavailable");
  }
  if (!controlManagerRunning) workerIssues.push("Control Manager not running");
  if (!dataWorkerRunning) workerIssues.push("Data Worker not running");
  
  // Check if Python engine is completely unavailable (no data at all from health check)
  const pythonEngineAvailable = (pythonEngine !== undefined && pythonEngine !== null) || serviceHealthReady;
  
  // Position Guardian status - monitors positions even when bot is stopped
  const positionGuardian = workers.position_guardian;
  const guardianSnapshot =
    // Primary: from live-status API (top level)
    (healthData as any)?.liveStatus?.position_guardian ||
    // Fallback: nested under health
    (healthData as any)?.liveStatus?.health?.position_guardian ||
    (healthData as any)?.services?.position_guardian ||
    // Some APIs expose a top-level position_guardian in the health payload
    (healthData as any)?.position_guardian;
  const guardianStatus = String(guardianSnapshot?.status ?? "").toLowerCase();
  const guardianReason = guardianSnapshot?.reason;
  const guardianRunning =
    guardianStatus === 'running' ||
    positionGuardian?.status === 'running' ||
    positionGuardian?.status === 'ok' ||
    positionGuardian === 'running' ||
    positionGuardian === true;
  const guardianMisconfigured = guardianStatus === 'misconfigured';
  const guardianConfig = guardianSnapshot?.config || {};
  const guardianMaxAgeSec = Number(guardianConfig?.maxAgeSec ?? 0);
  const guardianHardMaxAgeSec = Number(guardianConfig?.hardMaxAgeSec ?? 0);
  const guardianContinuationEnabled = Boolean(guardianConfig?.continuationEnabled);
  const guardianConfirmations = Number(guardianConfig?.maxAgeConfirmations ?? 1);

  const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  const notifyCommandResult = async (label: string, commandId?: string) => {
    if (!commandId || !runBarBotId) return;
    try {
      await delay(1200);
      const results = await fetchCommandResults({ botId: runBarBotId, commandId, limit: 5 });
      const latest = results.find((r) => r.command_id === commandId) || results[0];
      if (!latest) return;
      if (latest.status === "succeeded") {
        toast.success(`${label} succeeded`);
      } else if (latest.status === "failed") {
        toast.error(`${label} failed: ${latest.message || "error"}`);
      } else {
        toast(`${label}: ${latest.status}`);
      }
    } catch (err: any) {
      toast.error(`Failed to read ${label.toLowerCase()} status`);
    }
  };
  
  // Mutations
  const startMutation = useMutation({
    mutationFn: () => {
      if (!runBarBotId) throw new Error("No bot configured for this exchange");
      return startBotById(runBarBotId, {
        exchangeAccountId: runBarExchangeAccountId || undefined,
        botExchangeConfigId: runBarBotExchangeConfigId || undefined,
        configVersion: runtimeConfigVersion || (configVersion ? Number(configVersion) : undefined),
        enabledSymbols: (runtimeConfig?.enabled_symbols as string[]) || undefined,
        riskConfig: (runtimeConfig?.risk_config as Record<string, unknown>) || undefined,
        executionConfig: (runtimeConfig?.execution_config as Record<string, unknown>) || undefined,
        profileOverrides: (runtimeConfig?.profile_overrides as Record<string, unknown>) || undefined,
      });
    },
    onMutate: () => {
      // Open startup modal instead of toast
      const tradingModeLabel = botForExchange?.exchangeConfigs?.[0]?.environment || 'paper';
      startupModal.startStartup(displayBotName || 'Trading Bot', tradingModeLabel);
      setStartupWarning(null);
    },
    onSuccess: async (data) => {
      // Update modal to queued phase until health/WS catches up
      startupModal.updatePhase("initializing");
      toast.success("Start command queued");
      setQueuedCommandId(data.commandId || null);
      setWarmupLock(true);
      await notifyCommandResult("Start", data.commandId);
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      setQueuedCommandId(null);
      // Nudge modal forward once command succeeded; we'll continue advancing based on health/WS
      if (startupModal.isOpen) {
        startupModal.updatePhase("connecting");
      }
      // If health already shows running, jump to ready
      if (startupModal.isOpen && healthData?.status === "ok") {
        startupModal.updatePhase("ready");
      }
    },
    onError: (error: any) => {
      const respMsg =
        error?.response?.data?.error ||
        error?.response?.data?.message ||
        error?.message ||
        "Failed to start";
      
      // If start is already in progress, show progress instead of error
      if (respMsg === "start_in_progress") {
        // Bot is already starting - show progress modal and track it
        const tradingModeLabel = botForExchange?.exchangeConfigs?.[0]?.environment || 'paper';
        startupModal.startStartup(displayBotName || 'Trading Bot', tradingModeLabel);
        startupModal.updatePhase("initializing");
        toast("Bot startup already in progress", { icon: "⏳" });
        setWarmupLock(true);
        return;
      }
      
      startupModal.setError(respMsg);
      toast.error(respMsg);
      setWarmupLock(false);
    },
  });

  // Allow start if essential workers are up OR we have no health data yet (optimistic start)
  const canStart = !!runBarBotId && hasVerifiedCredential;
  const warmupTelemetryActive = runtimeHeartbeatActive || startLocked || warmupLock;
  const effectiveWarmupProgress = warmupTelemetryActive ? warmupProgress : 0;
  const warmupPending =
    startLocked ||
    (runtimeHeartbeatActive && !warmupReady && (warmupLock || warmupProgress > 0));
  const startDisabled =
    startMutation.isPending ||
    runtimeActuallyActive ||
    !canStart ||
    warmupPending ||
    dataIssues ||
    !!queuedCommandId;

  const applyRuntimeKnobValue = (knob: RuntimeKnobSpec, rawValue: string) => {
    setRuntimeConfig((prev) => {
      if (!prev) return prev;
      const next = { ...prev } as Record<string, any>;
      const section = { ...(next[knob.section] || {}) };
      const writeKey = resolveWriteKey(section, knob.key);
      let parsed: unknown = rawValue;
      if (knob.type === "int") {
        parsed = rawValue === "" ? null : parseInt(rawValue, 10);
      } else if (knob.type === "float") {
        parsed = rawValue === "" ? null : parseFloat(rawValue);
      } else if (knob.type === "bool") {
        parsed = rawValue === "true";
      }
      section[writeKey] = parsed;
      next[knob.section] = section;
      return next;
    });
  };

  const handleApplyRuntimeConfig = async () => {
    if (!runBarBotExchangeConfigId || !runtimeConfig) {
      toast.error("No exchange config selected");
      return;
    }
    if (runtimeValidationErrors.length) {
      setRuntimeConfigError(runtimeValidationErrors[0]);
      return;
    }
    setRuntimeConfigSaving(true);
    setRuntimeConfigError(null);
    try {
      const symbols = runtimeEnabledSymbols
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const result = await applyRuntimeConfig({
        botExchangeConfigId: runBarBotExchangeConfigId,
        enabledSymbols: symbols,
        riskConfig: (runtimeConfig.risk_config as Record<string, unknown>) || {},
        executionConfig: (runtimeConfig.execution_config as Record<string, unknown>) || {},
        profileOverrides: (runtimeConfig.profile_overrides as Record<string, unknown>) || {},
      });
      setRuntimeConfig(result.config as unknown as Record<string, unknown>);
      setRuntimeConfigVersion(result.config?.config_version ?? null);
      toast.success(`Runtime config applied (v${result.config?.config_version ?? "?"})`);
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
    } catch (err: any) {
      const msg = formatApiError(err, "Failed to apply runtime config");
      setRuntimeConfigError(msg);
      toast.error(msg);
    } finally {
      setRuntimeConfigSaving(false);
    }
  };
  
  // Track startup phases for modal
  const prevTradingActiveRef = useRef(isTradingActive);
  useEffect(() => {
    // Only track when modal is open
    if (!startupModal.isOpen) return;
    
    // Phase progression based on actual state
    if (startupModal.phase === "initializing") {
      // Check if websocket is connected
      if (wsConnected || fastScalper?.websocket?.publicConnected) {
        startupModal.updatePhase("connecting");
      }
    }
    
    if (startupModal.phase === "connecting") {
      // Move to warmup once we have websocket and bot is showing activity
      if (runtimeActuallyActive || (runtimeHeartbeatActive && warmupProgress > 0) || serviceHealthReady || essentialWorkersRunning) {
        startupModal.updatePhase("warmup");
      }
    }
    
    if (startupModal.phase === "warmup") {
      // Check if warmup is complete
      if (warmupReady && botRuntimeHealthy) {
        startupModal.updatePhase("ready");
      }
    }
    
    // Also detect if bot just became active (fast path)
    if (!prevTradingActiveRef.current && runtimeActuallyActive && startupModal.phase !== "ready") {
      if (warmupReady) {
        startupModal.updatePhase("ready");
      } else if (runtimeHeartbeatActive && warmupProgress > 0) {
        startupModal.updatePhase("warmup");
      } else {
        startupModal.updatePhase("connecting");
      }
    }
    
    if (startupModal.phase !== "ready" && warmupReady && botRuntimeHealthy) {
      startupModal.updatePhase("ready");
    }
    
    prevTradingActiveRef.current = runtimeActuallyActive;
  }, [
    startupModal.isOpen, 
    startupModal.phase, 
    wsConnected, 
    fastScalper?.websocket?.publicConnected,
    runtimeActuallyActive, 
    warmupProgress, 
    warmupReady,
    runtimeHeartbeatActive,
    botRuntimeHealthy,
    startupModal
  ]);

  // Startup timeout / warning if warming too long
  useEffect(() => {
    if (!startupModal.isOpen) return;
    if (!["connecting", "warmup"].includes(startupModal.phase)) return;
    const timer = setTimeout(() => {
      setStartupWarning("Warmup taking longer than expected. Check data feeds/quality.");
    }, 20000);
    return () => clearTimeout(timer);
  }, [startupModal.isOpen, startupModal.phase]);
  
  // Handle cancel startup
  const handleCancelStartup = () => {
    startupModal.cancel();
    // If bot is starting, attempt to stop it
    if (startMutation.isPending) {
      // Can't really cancel the mutation, but we mark as cancelled
    } else if (isTradingActive && runBarBotId) {
      stopMutation.mutate();
    }
  };

  const stopMutation = useMutation({
    mutationFn: () => {
      if (!runBarBotId) throw new Error("No bot configured for this exchange");
      return stopBotById(runBarBotId, { exchangeAccountId: runBarExchangeAccountId || undefined });
    },
    onSuccess: async (data) => {
      toast.success("Stop command queued");
      setQueuedCommandId(data.commandId || null);
      await notifyCommandResult("Stop", data.commandId);
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      setQueuedCommandId(null);
    },
    onError: (error: Error) => toast.error(error.message || "Failed to pause"),
  });

  const emergencyStopMutation = useMutation({
    mutationFn: async () => {
      // 1. Trigger kill switch first to immediately block all new decisions
      try {
        await triggerKillSwitch({ 
          trigger: "manual", 
          message: "Emergency halt from dashboard" 
        });
      } catch (err) {
        console.warn("[HALT] Kill switch trigger failed, continuing with stop:", err);
        // Continue even if kill switch fails - stopping the bot is still important
      }
      
      // 2. Stop the bot
      if (runBarBotId) {
        return stopBotById(runBarBotId, { exchangeAccountId: runBarExchangeAccountId || undefined });
      }
      return { success: true };
    },
    onSuccess: async (data) => {
      toast.success("Emergency halt executed - Kill switch activated");
      if (data?.commandId) {
        await notifyCommandResult("Halt", data.commandId);
      }
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["quant", "killSwitch"] });
    },
    onError: (error: Error) => toast.error(error.message || "Emergency halt failed"),
  });

  const cancelAllOrdersMutation = useMutation({
    mutationFn: () => cancelAllOrders({ botId: runBarBotId || undefined, exchangeAccountId: runBarExchangeAccountId || undefined }),
    onSuccess: (data) => {
      toast.success(`Cancelled ${data.cancelled || 0} orders`);
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
    },
    onError: (error: Error) => toast.error(error.message || "Failed to cancel orders"),
  });

  const flattenAllMutation = useMutation({
    mutationFn: () => closeAllPositions({ botId: runBarBotId || undefined, exchangeAccountId: runBarExchangeAccountId || undefined }),
    onSuccess: (data) => {
      const total = (data.paperClosed || 0) + (data.exchangeClosed || 0) + (data.count || 0);
      const ambiguous = (data as any).ambiguous || 0;
      if (total > 0) {
        toast.success(`Closed ${total} position(s)${ambiguous > 0 ? `, skipped ${ambiguous} ambiguous` : ""}`);
      } else if (ambiguous > 0) {
        toast.error(`Skipped ${ambiguous} ambiguous position(s); no bot-owned positions were closed`);
      } else {
        toast.error(data.message || "No positions were closed");
      }
      queryClient.invalidateQueries({ queryKey: ["ops-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
    },
    onError: (error: Error) => toast.error(error.message || "Failed to flatten positions"),
  });

  // Format helpers
  const formatHeartbeat = () => {
    if (lastHeartbeatAgeSec !== null && lastHeartbeatAgeSec !== undefined) {
      if (lastHeartbeatAgeSec < 60) return `${Math.floor(lastHeartbeatAgeSec)}s`;
      if (lastHeartbeatAgeSec < 3600) return `${Math.floor(lastHeartbeatAgeSec / 60)}m`;
    }
    if (!lastHeartbeat) return "—";
    const diff = Date.now() - new Date(lastHeartbeat).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m`;
    return "—";
  };

  const formatLastDecision = () => {
    if (!lastDecision) return "—";
    
    let tsMs: number;
    if (typeof lastDecision === 'number') {
      // If it's a number less than year 2000 in ms (~946 billion), it's probably seconds
      tsMs = lastDecision < 946684800000 ? lastDecision * 1000 : lastDecision;
    } else if (typeof lastDecision === 'object') {
      // Object with timestamp field - could be from decision stream
      const ts = lastDecision.timestamp ?? lastDecision.payload?.timestamp;
      if (!ts) return "—";
      // If numeric timestamp, check if seconds or ms
      if (typeof ts === 'number') {
        tsMs = ts < 946684800000 ? ts * 1000 : ts;
      } else {
        // String - try parsing (could be epoch string or ISO)
        const parsed = Number(ts);
        if (!isNaN(parsed)) {
          tsMs = parsed < 946684800000 ? parsed * 1000 : parsed;
        } else {
          tsMs = new Date(ts).getTime();
        }
      }
    } else {
      // String (ISO format) - parse directly, already gives ms
      tsMs = new Date(lastDecision).getTime();
    }
    
    const diff = Date.now() - tsMs;
    if (isNaN(diff) || diff < 0 || diff > 300000) return "—"; // Invalid or >5 min ago
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    return `${Math.floor(diff / 60000)}m ago`;
  };

  // Determine if we're in warming state (bot started but data not ready)
  const isWarming = runtimeActuallyActive && !warmupReady && effectiveWarmupProgress > 0;
  
  const getStatus = (): { status: "success" | "warning" | "error" | "neutral"; label: string; tooltip: string; isWarming?: boolean; hasBlockers?: boolean; workersDown?: boolean } => {
    if (!runBarBotId) return { status: "neutral", label: "No Bot", tooltip: "No bot configured for this exchange" };
    if (!hasVerifiedCredential) return { status: "warning", label: "No Creds", tooltip: "Exchange credentials not verified" };
    
    // Check Python workers when not trading - critical blocker
    if (!runtimeActuallyActive && !essentialWorkersRunning && pythonEngineAvailable !== undefined) {
      return { 
        status: "error", 
        label: "Stopped", 
        tooltip: workerIssues.length > 0 ? workerIssues.join(", ") : "Python workers not running",
        workersDown: true 
      };
    }
    // Show warmup status first - this is normal during startup
    if (warmupPending) {
      const tooltipParts = [];
      if (warmupReasons.length > 0) tooltipParts.push(`Status: ${warmupReasons.join(", ")}`);
      tooltipParts.push(`Progress: ${Math.round(effectiveWarmupProgress)}%`);
      return {
        status: "warning",
        label: `Warming ${Math.round(effectiveWarmupProgress)}%`,
        tooltip: tooltipParts.join(" | "),
        isWarming: true
      };
    }
    // Only show data issues AFTER warmup is complete and there are critical issues
    if (dataIssues) {
      return {
        status: "error",
        label: "Data Issues",
        tooltip: criticalDataIssues.join(", "),
        hasBlockers: true,
      };
    }
    
    if (runtimeActuallyActive) {
      // Check if still warming up
      if (isWarming) {
        const tooltipParts = [];
        if (warmupReasons.length > 0) tooltipParts.push(`Status: ${warmupReasons.join(", ")}`);
        tooltipParts.push(`Progress: ${Math.round(effectiveWarmupProgress)}%`);
        return { 
          status: "warning", 
          label: `Warming ${Math.round(effectiveWarmupProgress)}%`, 
          tooltip: tooltipParts.join(" | "), 
          isWarming: true 
        };
      }
      // Only show data issues after warmup complete with critical issues
      if (dataIssues) {
        return {
          status: "error",
          label: "Data Issues",
          tooltip: criticalDataIssues.join(", "),
          hasBlockers: true,
        };
      }
      // Check for trading blockers
      if (hasErrorBlocker) {
        const blocker = tradingBlockers.find((b: any) => b.severity === 'error');
        return { 
          status: "error", 
          label: "Blocked", 
          tooltip: `${blocker?.blade}: ${blocker?.reason}`,
          hasBlockers: true 
        };
      }
      if (hasWarningBlocker) {
        const blocker = tradingBlockers.find((b: any) => b.severity === 'warning');
        return { 
          status: "warning", 
          label: "Throttled", 
          tooltip: `${blocker?.blade}: ${blocker?.reason}`,
          hasBlockers: true 
        };
      }
      if (!wsConnected) return { status: "warning", label: "Offline", tooltip: "Bot is running but WebSocket disconnected" };
      return { status: "success", label: "Running", tooltip: "Bot is actively trading" };
    }
    if (platformStatus === "error") return { status: "error", label: "Error", tooltip: "Bot encountered an error" };
    return { status: "neutral", label: "Stopped", tooltip: "Bot is not running" };
  };

  const currentStatus = getStatus();

  // Derive a data-quality/warmup message for the startup modal
  const dataQualityWarning = useMemo(() => {
    if (startupWarning) return startupWarning;
    if (!healthData) return null;
    const status = String((healthData as any)?.status ?? "").trim().toLowerCase();
    const actionableHealthStatuses = new Set(["error", "failed", "stopped", "auth_failed", "config_drift", "degraded"]);
    if (actionableHealthStatuses.has(status)) {
      return `Health status: ${status}`;
    }
    const queueOverflow = (healthData as any)?.queue_overflow;
    if (queueOverflow) return "Queues are backed up; warmup may be delayed.";
    return null;
  }, [healthData, startupWarning]);

  // Fleet view - show minimal status
  if (scopeLevel === 'fleet') {
    return (
      <TooltipProvider delayDuration={0}>
        <div className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
          <div className="flex h-12 items-center justify-between px-4 lg:px-6">
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="font-normal">
                Fleet View
              </Badge>
              <span className="text-sm text-muted-foreground">
                {(exchangeAccounts as any[]).length} accounts · {allBots.length} bots
              </span>
            </div>
            <Link to="/exchange-accounts">
              <Button variant="outline" size="sm" className="gap-1.5">
                <Settings className="h-3.5 w-3.5" />
                Manage
              </Button>
            </Link>
          </div>
        </div>
      </TooltipProvider>
    );
  }

  // Minimal variant - just a simple link bar for non-trading pages (Analysis, Research, Settings)
  if (variant === "minimal") {
    return (
      <TooltipProvider delayDuration={0}>
        <div className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
          <div className="flex h-10 items-center justify-between px-4 lg:px-6">
            <div className="flex items-center gap-3">
              {exchange && <ExchangeLogo venue={exchange} className="h-4 w-4" />}
              <span className="text-sm font-medium">{accountLabel}</span>
              <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                {environment.toUpperCase()}
              </Badge>
              {displayBotName && (
                <>
                  <span className="text-muted-foreground">·</span>
                  <Bot className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{displayBotName}</span>
                </>
              )}
              <span className="text-muted-foreground">·</span>
              <div className={cn(
                "flex items-center gap-1.5",
                currentStatus.status === "success" ? "text-emerald-600 dark:text-emerald-400" :
                currentStatus.status === "warning" ? "text-amber-600 dark:text-amber-400" :
                currentStatus.status === "error" ? "text-red-600 dark:text-red-400" :
                "text-muted-foreground"
              )}>
                <span className={cn(
                  "h-2 w-2 rounded-full",
                  currentStatus.status === "success" ? "bg-emerald-500" :
                  currentStatus.status === "warning" ? "bg-amber-500" :
                  currentStatus.status === "error" ? "bg-red-500" :
                  "bg-muted-foreground/50",
                  isTradingActive && currentStatus.status === "success" && "animate-pulse"
                )} />
                <span className="text-xs font-medium">{currentStatus.label}</span>
              </div>
            </div>
            <Link to="/live">
              <Button variant="outline" size="sm" className="gap-1.5 h-7 text-xs">
                <Activity className="h-3 w-3" />
                Bot Controls
                <ChevronRight className="h-3 w-3" />
              </Button>
            </Link>
          </div>
        </div>
      </TooltipProvider>
    );
  }

  // Compact variant for non-trading pages
  if (variant === "compact") {
    return (
      <TooltipProvider delayDuration={0}>
        <Link to="/" className="block">
          <div className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80 hover:bg-card transition-colors">
            <div className="flex h-10 items-center justify-between px-4 lg:px-6">
              <div className="flex items-center gap-3">
                {exchange && <ExchangeLogo venue={exchange} className="h-4 w-4" />}
                <span className="text-sm font-medium">{accountLabel}</span>
                <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                  {environment.toUpperCase()}
                </Badge>
                {displayBotName && (
                  <>
                    <span className="text-muted-foreground">·</span>
                    <span className="text-sm text-muted-foreground">{displayBotName}</span>
                  </>
                )}
                <span className="text-muted-foreground">·</span>
                {currentStatus.workersDown ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="text-xs flex items-center gap-1 cursor-pointer text-red-500">
                        <AlertTriangle className="h-3 w-3" />
                        {currentStatus.label}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="p-3 max-w-xs">
                      <div className="space-y-1.5">
                        <div className="font-semibold text-sm text-red-500">Python Workers Unavailable</div>
                        <ul className="text-xs space-y-0.5 text-muted-foreground">
                          {workerIssues.map((issue, i) => (
                            <li key={i}>• {issue}</li>
                          ))}
                        </ul>
                      </div>
                    </TooltipContent>
                  </Tooltip>
                ) : currentStatus.isWarming ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="flex items-center gap-1.5 cursor-default">
                        <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                        <span className="text-sm font-medium text-amber-600 dark:text-amber-400">
                          {currentStatus.label}
                        </span>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" align="start" className="p-3">
                      <WarmupTooltipContent warmupData={warmupData} />
                    </TooltipContent>
                  </Tooltip>
                ) : currentStatus.hasBlockers ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className={cn(
                        "text-xs flex items-center gap-1 cursor-pointer",
                        currentStatus.status === "error" ? "text-red-500" : "text-amber-500"
                      )}>
                        <AlertTriangle className="h-3 w-3" />
                        {currentStatus.label}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="p-3 max-w-sm">
                      <div className="space-y-2">
                        <div className="font-semibold text-sm">Trading Blockers</div>
                        {tradingBlockers.map((blocker: any, i: number) => (
                          <div key={i} className="flex items-start gap-2">
                            <div className={cn(
                              "h-2 w-2 rounded-full mt-1.5 shrink-0",
                              blocker.severity === 'error' ? "bg-red-500" : "bg-amber-500"
                            )} />
                            <div>
                              <div className="font-medium text-sm">{blocker.blade}</div>
                              <div className="text-xs text-muted-foreground">{blocker.reason}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <StatusPill 
                    status={currentStatus.status} 
                    label={currentStatus.label} 
                    tooltip={currentStatus.tooltip}
                    pulse={currentStatus.status === "success"} 
                  />
                )}
                {/* Only show Data Ready when stopped but data is ready */}
                {!isTradingActive && warmupReady && (
                  <>
                    <span className="text-muted-foreground">·</span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-xs text-emerald-500 flex items-center gap-1 cursor-default">
                          <CheckCircle2 className="h-3 w-3" />
                          Data Ready
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="p-3">
                        <WarmupTooltipContent warmupData={warmupData} />
                      </TooltipContent>
                    </Tooltip>
                  </>
                )}
                {/* Show 24h PnL in compact view */}
                {(dailyPnl !== 0 || isTradingActive) && (
                  <>
                    <span className="text-muted-foreground">·</span>
                    <span className={cn(
                      "text-xs font-mono font-medium",
                      dailyPnl >= 0 ? "text-emerald-500" : "text-red-500"
                    )}>
                      {dailyPnl >= 0 ? "+" : ""}{dailyPnlPct.toFixed(1)}%
                    </span>
                  </>
                )}
              </div>
              <span className="text-xs text-muted-foreground">Click to control →</span>
            </div>
          </div>
        </Link>
      </TooltipProvider>
    );
  }

  // Full variant for trading pages
  return (
    <TooltipProvider delayDuration={0}>
      <div className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
        <div className="flex h-14 items-center gap-4 px-4 lg:px-6">
          {/* Bot Config Button - Opens sheet with current config */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button 
                variant="outline" 
                size="sm" 
                className="gap-2 h-8 hover:bg-muted"
                onClick={() => setConfigSheetOpen(true)}
              >
                {exchange && <ExchangeLogo venue={exchange} className="h-4 w-4" />}
                <span className="font-medium">{accountLabel}</span>
                <Badge 
                  variant="outline" 
                  className={cn(
                    "text-[10px] px-1.5 py-0 ml-1",
                    environment === "live" 
                      ? "border-red-500/50 bg-red-500/10 text-red-600 dark:text-red-400" 
                      : "border-blue-500/50 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                  )}
                >
                  {environment.toUpperCase()}
                </Badge>
                {displayBotName && (
                  <>
                    <span className="text-muted-foreground mx-1">·</span>
                    <Bot className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-sm">{displayBotName}</span>
                    {configVersion && (
                      <span className="text-[10px] font-mono text-muted-foreground">v{configVersion}</span>
                    )}
                  </>
                )}
                <ChevronRight className="h-3 w-3 text-muted-foreground ml-1" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>View bot configuration</TooltipContent>
          </Tooltip>

          {/* Separator */}
          <div className="h-6 w-px bg-border" />

          {/* Status - includes warming progress in label when applicable */}
          {currentStatus.workersDown ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1.5 cursor-pointer">
                  <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
                  <span className="text-xs font-medium text-red-600 dark:text-red-400">
                    {currentStatus.label}
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="start" className="p-3 max-w-sm">
                <div className="space-y-2">
                  <div className="font-semibold text-sm text-red-500">Python Workers Unavailable</div>
                  <div className="text-xs text-muted-foreground mb-2">
                    The bot cannot start because essential Python services are not running.
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <div className={cn(
                        "h-2 w-2 rounded-full shrink-0",
                        controlManagerRunning ? "bg-emerald-500" : "bg-red-500"
                      )} />
                      <span className="text-sm">Control Manager</span>
                      <span className={cn(
                        "text-xs ml-auto",
                        controlManagerRunning ? "text-emerald-500" : "text-red-500"
                      )}>
                        {controlManagerRunning ? "Running" : "Stopped"}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className={cn(
                        "h-2 w-2 rounded-full shrink-0",
                        dataWorkerRunning ? "bg-emerald-500" : "bg-red-500"
                      )} />
                      <span className="text-sm">Data Worker</span>
                      <span className={cn(
                        "text-xs ml-auto",
                        dataWorkerRunning ? "text-emerald-500" : "text-red-500"
                      )}>
                        {dataWorkerRunning ? "Running" : "Stopped"}
                      </span>
                    </div>
                  </div>
                  <div className="pt-2 border-t text-[10px] text-muted-foreground">
                    Start Python services on the worker machine to enable trading.
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
          ) : currentStatus.isWarming ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1.5 cursor-default">
                  <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                  <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
                    {currentStatus.label}
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="start" className="p-3">
                <WarmupTooltipContent warmupData={warmupData} />
              </TooltipContent>
            </Tooltip>
          ) : currentStatus.hasBlockers ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1.5 cursor-pointer">
                  <AlertTriangle className={cn(
                    "h-3.5 w-3.5",
                    currentStatus.status === "error" ? "text-red-500" : "text-amber-500"
                  )} />
                  <span className={cn(
                    "text-xs font-medium",
                    currentStatus.status === "error" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                  )}>
                    {currentStatus.label}
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="start" className="p-3 max-w-sm">
                <div className="space-y-2">
                  <div className="font-semibold text-sm">Trading Blockers</div>
                  {tradingBlockers.map((blocker: any, i: number) => (
                    <div key={i} className="flex items-start gap-2">
                      <div className={cn(
                        "h-2 w-2 rounded-full mt-1.5 shrink-0",
                        blocker.severity === 'error' ? "bg-red-500" : "bg-amber-500"
                      )} />
                      <div>
                        <div className="font-medium text-sm">{blocker.blade}</div>
                        <div className="text-xs text-muted-foreground">{blocker.reason}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </TooltipContent>
            </Tooltip>
          ) : (
            <StatusPill 
              status={currentStatus.status} 
              label={currentStatus.label} 
              tooltip={currentStatus.tooltip}
              pulse={currentStatus.status === "success"} 
            />
          )}

          {/* Data Ready - only show when NOT running (redundant if running) and data is actually ready */}
          {!isTradingActive && warmupReady && (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 cursor-default">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span className="text-xs font-medium">Data Ready</span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="start" className="p-3">
                <WarmupTooltipContent warmupData={warmupData} />
              </TooltipContent>
            </Tooltip>
          )}

          {/* Position Guardian Status - shows protection status always */}
          <Tooltip>
            <TooltipTrigger asChild>
              <div className={cn(
                "flex items-center gap-1.5 cursor-default",
                guardianMisconfigured
                  ? "text-red-600 dark:text-red-400"
                  : guardianRunning 
                  ? "text-emerald-600 dark:text-emerald-400" 
                  : "text-amber-600 dark:text-amber-400"
              )}>
                <Shield className={cn("h-3.5 w-3.5", guardianRunning && !guardianMisconfigured && "animate-pulse")} />
                <span className="text-xs font-medium">
                  {guardianMisconfigured ? "Guard Misconfigured" : guardianRunning ? "Guarded" : "Unguarded"}
                </span>
                {guardianMaxAgeSec > 0 && (
                  <span className="text-[10px] opacity-80">
                    {`Max Age ${formatDurationShort(guardianMaxAgeSec)}`}
                  </span>
                )}
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="start" className="p-3 max-w-xs">
              <div className="space-y-2">
                <div className="font-semibold text-sm flex items-center gap-2">
                  <Shield className="h-4 w-4" />
                  Position Guardian
                </div>
                {guardianMisconfigured ? (
                  <div className="space-y-1.5 text-xs">
                    <p className="text-red-500">Misconfigured</p>
                    <p className="text-muted-foreground">
                      Live trading is running without a valid position-guard policy. Max age exits may not fire.
                    </p>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 pt-1 text-[11px]">
                      <span className="text-muted-foreground">Reason</span>
                      <span>{guardianReason || "invalid_guard_policy"}</span>
                      <span className="text-muted-foreground">Max Age</span>
                      <span>{guardianMaxAgeSec > 0 ? formatDurationShort(guardianMaxAgeSec) : "off"}</span>
                      <span className="text-muted-foreground">Hard Cap</span>
                      <span>{guardianHardMaxAgeSec > 0 ? formatDurationShort(guardianHardMaxAgeSec) : "off"}</span>
                    </div>
                  </div>
                ) : guardianRunning ? (
                  <div className="space-y-1.5 text-xs">
                    <p className="text-emerald-500">✅ Active - Monitoring positions</p>
                    <p className="text-muted-foreground">
                      SL/TP orders are verified every 30 seconds.
                      Positions will be protected even when trading is paused.
                    </p>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 pt-1 text-[11px]">
                      <span className="text-muted-foreground">Max Age</span>
                      <span>{guardianMaxAgeSec > 0 ? formatDurationShort(guardianMaxAgeSec) : "off"}</span>
                      <span className="text-muted-foreground">Hard Cap</span>
                      <span>{guardianHardMaxAgeSec > 0 ? formatDurationShort(guardianHardMaxAgeSec) : "off"}</span>
                      <span className="text-muted-foreground">Confirmations</span>
                      <span>{Number.isFinite(guardianConfirmations) ? guardianConfirmations : 1}</span>
                      <span className="text-muted-foreground">Continuation</span>
                      <span>{guardianContinuationEnabled ? "on" : "off"}</span>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1.5 text-xs">
                    <p className="text-amber-500">⚠️ Not running</p>
                    <p className="text-muted-foreground">
                      Position protection is inactive. Existing positions may not have 
                      SL/TP orders verified. Start Python workers to enable protection.
                    </p>
                  </div>
                )}
              </div>
            </TooltipContent>
          </Tooltip>

          {/* Financial metrics (Balance/Capital) hidden for now */}

          {/* Spacer */}
          <div className="flex-1" />

          {/* Health Metrics (only when trading) */}
          {isTradingActive && (
            <div className="hidden md:flex items-center gap-2">
              <MetricChip 
                icon={Activity} 
                label="Heartbeat" 
                value={formatHeartbeat()}
                tooltip="Time since last heartbeat from trading engine"
                status={!lastHeartbeat ? "warning" : "neutral"}
              />
              <MetricChip 
                icon={Clock} 
                label="Last Decision" 
                value={formatLastDecision()}
                tooltip="Time since last trading decision"
              />
              {evalRate > 0 && (
                <MetricChip 
                  icon={Zap} 
                  label="Eval Rate" 
                  value={`${evalRate.toFixed(0)}/s`}
                  tooltip="Decision evaluations per second"
                />
              )}
              {p95Latency > 0 && (
                <MetricChip 
                  icon={Timer} 
                  label="p95" 
                  value={`${p95Latency.toFixed(0)}µs`}
                  tooltip="95th percentile decision latency"
                />
              )}
            </div>
          )}

          {/* Controls */}
          <div className="flex items-center gap-2">
            {/* State indicator */}
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 border">
                <div className={cn(
                  "h-2 w-2 rounded-full",
                  runtimeActuallyActive || warmupPending ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground/50"
                )} />
                <span className="text-xs font-medium">
                  {startMutation.isPending ? "Starting..." : 
                   stopMutation.isPending ? "Stopping..." :
                   warmupPending ? "Warming up..." :
                   runtimeActuallyActive ? `Running (${tradingModeLabel})` : `Stopped (${tradingModeLabel})`}
                </span>
                {queuedCommandId && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-700">
                    Queued
                  </span>
                )}
              </div>

            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5"
              onClick={() => {
                if (!runBarBotExchangeConfigId) {
                  toast.error("No active exchange config found. Select a bot scope first.");
                  return;
                }
                setRuntimeConfigOpen(true);
              }}
            >
              <Settings className="h-3.5 w-3.5" />
              Config
            </Button>

            {/* Main controls */}
            <div className="flex items-center gap-1">
              {/* Run button - only show when not running */}
              {!runtimeActuallyActive && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-1.5"
                      disabled={startDisabled || startMutation.isPending}
                      onClick={() => {
                        if (!essentialWorkersRunning) {
                          const reasons = workerIssues.length ? workerIssues.join(", ") : "Python workers not ready";
                          toast.error(reasons);
                          return;
                        }
                        startMutation.mutate();
                      }}
                    >
                      <Play className="h-3.5 w-3.5 text-emerald-500" />
                      {warmupPending ? "Warming..." : startMutation.isPending ? "..." : "Run"}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {!runBarBotId ? "No bot configured" :
                     !hasVerifiedCredential ? "Credentials not verified" :
                     warmupPending ? "Warming up data; waiting on samples/candles" :
                     !essentialWorkersRunning ? (
                       <div className="space-y-1">
                         <div className="font-medium text-red-400">Python workers not ready</div>
                         <ul className="text-xs space-y-0.5">
                           {workerIssues.map((issue, i) => (
                             <li key={i}>• {issue}</li>
                           ))}
                         </ul>
                         <div className="text-xs text-muted-foreground">Clicking Run will still attempt to start.</div>
                       </div>
                     ) :
                     `Start ${displayBotName || 'bot'}`}
                  </TooltipContent>
                </Tooltip>
              )}

              {/* Pause button - only show when running */}
              {runtimeActuallyActive && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-1.5"
                      disabled={stopMutation.isPending || !runBarBotId}
                      onClick={() => stopMutation.mutate()}
                    >
                      <Pause className="h-3.5 w-3.5 text-amber-500" />
                      {stopMutation.isPending ? "..." : "Pause"}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Stop trading gracefully (keeps positions)</TooltipContent>
                </Tooltip>
              )}

              {/* Halt button with confirmation */}
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 border-red-500/30 hover:bg-red-500/10"
                    disabled={!runtimeActuallyActive || emergencyStopMutation.isPending}
                  >
                    <Square className="h-3.5 w-3.5 text-red-500" />
                    Halt
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle className="flex items-center gap-2">
                      <AlertTriangle className="h-5 w-5 text-red-500" />
                      Emergency Halt
                    </AlertDialogTitle>
                    <AlertDialogDescription className="space-y-3">
                      <p>This will <strong>immediately activate the kill switch</strong> and stop the bot.</p>
                      
                      <div className="space-y-2">
                        <div className="flex items-start gap-2 p-2 rounded-lg bg-red-500/10 border border-red-500/30">
                          <AlertTriangle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                          <div className="text-xs text-red-600 dark:text-red-400">
                            <p className="font-medium">Kill switch will block all trading:</p>
                            <ul className="mt-1 ml-2 space-y-0.5">
                              <li>• No new positions can be opened</li>
                              <li>• No new orders will be placed</li>
                              <li>• Existing positions remain open</li>
                            </ul>
                          </div>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          You can reset the kill switch from the Safety panel when you're ready to resume trading.
                        </p>
                      </div>
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={() => emergencyStopMutation.mutate()}
                      className="bg-red-500 hover:bg-red-600 disabled:opacity-50"
                      disabled={!runtimeActuallyActive || emergencyStopMutation.isPending}
                    >
                      {emergencyStopMutation.isPending ? "Halting..." : "Halt & Activate Kill Switch"}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>

            {/* Quick actions dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="h-8 px-2">
                  <span className="sr-only">More actions</span>
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <DropdownMenuItem
                      onSelect={(e) => e.preventDefault()}
                      className="gap-2"
                      disabled={cancelAllOrdersMutation.isPending}
                    >
                      <XCircle className="h-4 w-4 text-amber-500" />
                      <div className="flex-1">
                        <p>{cancelAllOrdersMutation.isPending ? "Cancelling..." : "Cancel All Orders"}</p>
                        <p className="text-[10px] text-muted-foreground">Cancel pending orders</p>
                      </div>
                    </DropdownMenuItem>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle className="flex items-center gap-2">
                        <XCircle className="h-5 w-5 text-amber-500" />
                        Cancel All Orders
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        This will cancel all pending and open orders. Existing positions will remain open.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => cancelAllOrdersMutation.mutate()}
                        className="bg-amber-500 hover:bg-amber-600"
                        disabled={cancelAllOrdersMutation.isPending}
                      >
                        {cancelAllOrdersMutation.isPending ? "Cancelling..." : "Cancel All Orders"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
                
                <DropdownMenuSeparator />
                
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <DropdownMenuItem
                      onSelect={(e) => e.preventDefault()}
                      className="gap-2"
                      disabled={flattenAllMutation.isPending}
                    >
                      <Layers className="h-4 w-4 text-red-500" />
                      <div className="flex-1">
                        <p>{flattenAllMutation.isPending ? "Flattening..." : "Flatten All Positions"}</p>
                        <p className="text-[10px] text-muted-foreground">Close all at market</p>
                      </div>
                    </DropdownMenuItem>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle className="flex items-center gap-2">
                        <Layers className="h-5 w-5 text-red-500" />
                        Flatten All Positions
                      </AlertDialogTitle>
                      <AlertDialogDescription className="space-y-3">
                        <p>
                          This will close all open positions with market orders.
                        </p>
                        
                        <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
                          <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                          <p className="text-xs text-amber-600 dark:text-amber-400">
                            Market orders may experience slippage. Consider using limit orders for large positions.
                          </p>
                        </div>
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => flattenAllMutation.mutate()}
                        className="bg-red-500 hover:bg-red-600"
                        disabled={flattenAllMutation.isPending}
                      >
                        {flattenAllMutation.isPending ? "Flattening..." : "Flatten All"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </DropdownMenuContent>
            </DropdownMenu>

          </div>
        </div>
      </div>

      {/* Bot Configuration Sheet */}
      <Sheet open={configSheetOpen} onOpenChange={setConfigSheetOpen}>
        <SheetContent side="right" className="w-[400px] sm:w-[540px]">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              Bot Configuration
            </SheetTitle>
            <SheetDescription>
              {runtimeActuallyActive ? "Currently running configuration" : "Configuration that will run on start"}
            </SheetDescription>
          </SheetHeader>

          <div className="mt-6 space-y-6">
            {/* Exchange Account Section */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Info className="h-4 w-4" />
                Exchange Account
              </div>
              <div className="rounded-lg border bg-card p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Account</span>
                  <div className="flex items-center gap-2">
                    {exchange && <ExchangeLogo venue={exchange} className="h-4 w-4" />}
                    <span className="font-medium">{accountLabel}</span>
                  </div>
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Exchange</span>
                  <span className="font-medium capitalize">{exchange || "—"}</span>
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Environment</span>
                  <Badge 
                    variant="outline" 
                    className={cn(
                      "text-xs",
                      environment === "live" 
                        ? "border-red-500/50 bg-red-500/10 text-red-600" 
                        : "border-blue-500/50 bg-blue-500/10 text-blue-600"
                    )}
                  >
                    {environment.toUpperCase()}
                  </Badge>
                </div>
                <Separator />
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Status</span>
                  <Badge variant={hasVerifiedCredential ? "default" : "outline"} className={cn(
                    "text-xs",
                    hasVerifiedCredential ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/50" : ""
                  )}>
                    {hasVerifiedCredential ? "Verified" : "Not Verified"}
                  </Badge>
                </div>
              </div>
            </div>

            {/* Active Bot Section */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Bot className="h-4 w-4" />
                Active Bot
              </div>
              <div className="rounded-lg border bg-card p-4 space-y-3">
                {botForExchange ? (
                  <>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Name</span>
                      <span className="font-medium">{botForExchange.name}</span>
                    </div>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Config Version</span>
                      <span className="font-mono text-sm">v{configVersion || "—"}</span>
                    </div>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Runtime State</span>
                      <Badge variant="outline" className={cn(
                        "text-xs capitalize",
                        botForExchange.runtime_state === "running" && "bg-emerald-500/10 text-emerald-600 border-emerald-500/50",
                        botForExchange.runtime_state === "paused" && "bg-amber-500/10 text-amber-600 border-amber-500/50",
                        botForExchange.runtime_state === "idle" && "bg-zinc-500/10 text-zinc-600 border-zinc-500/50"
                      )}>
                        {botForExchange.runtime_state || "idle"}
                      </Badge>
                    </div>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Mode</span>
                      <span className="font-medium capitalize">{runBarConfigForExchange?.mode || "fast"}</span>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-4">
                    <Bot className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                    <p className="text-sm text-muted-foreground">No bot configured for this exchange</p>
                    <Link to="/bot-management">
                      <Button variant="outline" size="sm" className="mt-3">
                        Configure Bot
                      </Button>
                    </Link>
                  </div>
                )}
              </div>
            </div>

            {/* Trading Symbols */}
            {runBarConfigForExchange?.symbols && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Target className="h-4 w-4" />
                  Trading Symbols
                </div>
                <div className="rounded-lg border bg-card p-4">
                  <div className="flex flex-wrap gap-2">
                    {((runBarConfigForExchange?.symbols || []) as string[]).map((symbol: string) => (
                      <Badge key={symbol} variant="outline" className="font-mono text-xs">
                        {symbol}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Risk Parameters */}
            {botForExchange?.exchangeConfigs?.[0] && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Shield className="h-4 w-4" />
                  Risk Parameters
                </div>
                <div className="rounded-lg border bg-card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Max Position Size</span>
                    <span className="font-mono text-sm">
                      ${botForExchange.exchangeConfigs[0].max_position_usd?.toLocaleString() || "—"}
                    </span>
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Max Daily Loss</span>
                    <span className="font-mono text-sm">
                      ${botForExchange.exchangeConfigs[0].max_daily_loss_usd?.toLocaleString() || "—"}
                    </span>
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Max Leverage</span>
                    <span className="font-mono text-sm">
                      {botForExchange.exchangeConfigs[0].max_leverage || "—"}x
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Financial Overview */}
            {(exchangeBalance > 0 || tradingCapital > 0) && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Wallet className="h-4 w-4" />
                  Financial Overview
                  {isPaperAccount && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-blue-500/50 text-blue-500">
                      PAPER
                    </Badge>
                  )}
                </div>
                <div className={cn(
                  "rounded-lg border bg-card p-4 space-y-3",
                  isPaperAccount && "border-blue-500/30"
                )}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">
                      {isPaperAccount ? "Paper Capital" : "Exchange Balance"}
                    </span>
                    <span className="font-mono text-sm font-medium">
                      ${exchangeBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Trading Capital</span>
                    <span className="font-mono text-sm font-medium">
                      ${tradingCapital.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">24h P&L</span>
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "font-mono text-sm font-medium",
                        dailyPnl >= 0 ? "text-emerald-600" : "text-red-600"
                      )}>
                        {dailyPnl >= 0 ? "+" : ""}${dailyPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                      <Badge variant="outline" className={cn(
                        "text-xs font-mono",
                        dailyPnl >= 0 
                          ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/50" 
                          : "bg-red-500/10 text-red-600 border-red-500/50"
                      )}>
                        {dailyPnl >= 0 ? "+" : ""}{dailyPnlPct.toFixed(2)}%
                      </Badge>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Current Metrics (when running) */}
            {runtimeActuallyActive && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Activity className="h-4 w-4" />
                  Live Metrics
                </div>
                <div className="rounded-lg border bg-card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">Eval Rate</span>
                    <span className="font-mono text-sm">{evalRate?.toFixed(1) || "0"}/s</span>
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">p95 Latency</span>
                    <span className="font-mono text-sm">{p95Latency ? `${p95Latency}µs` : "—"}</span>
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">WebSocket</span>
                    <Badge variant="outline" className={cn(
                      "text-xs",
                      wsConnected ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/50" : "bg-red-500/10 text-red-600 border-red-500/50"
                    )}>
                      {wsConnected ? "Connected" : "Disconnected"}
                    </Badge>
                  </div>
                </div>
              </div>
            )}

            {/* Footer Actions */}
            <div className="pt-4 border-t flex gap-3">
              <Link to="/exchange-accounts" className="flex-1">
                <Button variant="outline" className="w-full">
                  Manage Accounts
                </Button>
              </Link>
              <Link to="/bot-management" className="flex-1">
                <Button variant="outline" className="w-full">
                  Edit Bot
                </Button>
              </Link>
            </div>
          </div>
        </SheetContent>
      </Sheet>
      
      <Dialog open={runtimeConfigOpen} onOpenChange={(open) => {
        if (runtimeConfigSaving) return;
        setRuntimeConfigOpen(open);
      }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Runtime Config (Golden Source)</DialogTitle>
          </DialogHeader>
          {runtimeConfigLoading && <p className="text-sm text-muted-foreground">Loading...</p>}
          {runtimeConfigError && <p className="text-sm text-red-500">{runtimeConfigError}</p>}
          {!runtimeConfigLoading && !runtimeConfigError && (
            <div className="space-y-4">
              <div className="grid gap-2">
                <label className="text-xs font-medium text-muted-foreground">Enabled Symbols (comma-separated)</label>
                <Input
                  value={runtimeEnabledSymbols}
                  onChange={(e) => setRuntimeEnabledSymbols(e.target.value)}
                  placeholder="BTC-USDT-SWAP,ETH-USDT-SWAP,SOL-USDT-SWAP"
                />
              </div>
              <div className="max-h-[420px] overflow-auto rounded border p-3 space-y-3">
                {runtimeValidationErrors.length > 0 && (
                  <div className="rounded border border-red-500/40 bg-red-500/5 p-2 text-xs text-red-600 dark:text-red-400">
                    {runtimeValidationErrors.map((error, idx) => (
                      <p key={`${error}-${idx}`}>{error}</p>
                    ))}
                  </div>
                )}
                {runtimeKnobs.map((knob) => {
                  const section = (runtimeConfig?.[knob.section] || {}) as Record<string, any>;
                  const current = readKnobValue(section, knob.key);
                  const displayValue =
                    current === undefined || current === null || current === "" ? (knob.default ?? "") : current;
                  const fieldError = runtimeFieldErrors[`${knob.section}.${knob.key}`];
                  return (
                    <div
                      key={`${knob.section}.${knob.key}`}
                      className="grid grid-cols-1 md:grid-cols-[minmax(220px,1fr)_minmax(220px,1fr)] items-start gap-2"
                    >
                      <div className="min-w-0">
                        <p className="text-sm leading-5 break-words">{knob.label}</p>
                        <p className="text-[11px] text-muted-foreground font-mono break-all">{knob.section}.{knob.key}</p>
                      </div>
                      <div className="min-w-0">
                        {knob.type === "bool" ? (
                          <select
                            className="w-full rounded border bg-background px-2 py-1 text-sm"
                            value={displayValue === true ? "true" : "false"}
                            onChange={(e) => applyRuntimeKnobValue(knob, e.target.value)}
                          >
                            <option value="true">true</option>
                            <option value="false">false</option>
                          </select>
                        ) : (
                          <Input
                            type="number"
                            step={knob.type === "int" ? "1" : "0.0001"}
                            min={knob.min ?? undefined}
                            max={knob.max ?? undefined}
                            className={fieldError ? "border-red-500 focus-visible:ring-red-500" : undefined}
                            value={displayValue as any}
                            onChange={(e) => applyRuntimeKnobValue(knob, e.target.value)}
                          />
                        )}
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {knob.min != null || knob.max != null ? `Range: ${knob.min ?? "-inf"} to ${knob.max ?? "+inf"}` : "No range limit"}
                          {knob.default !== undefined && knob.default !== null ? ` | Default: ${String(knob.default)}` : ""}
                        </p>
                        {fieldError && <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">{fieldError}</p>}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  Active version: v{runtimeConfigVersion ?? "?"}. Applying creates a new config version.
                </p>
                <Button onClick={handleApplyRuntimeConfig} disabled={runtimeConfigSaving || runtimeValidationErrors.length > 0}>
                  {runtimeConfigSaving ? "Applying..." : "Apply Config"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      
      {/* Bot Startup Modal */}
      <BotStartupModal
        isOpen={startupModal.isOpen}
        onClose={startupModal.close}
        onCancel={handleCancelStartup}
        currentPhase={startupModal.phase}
        warmupProgress={warmupProgress}
        warmupDetail={{
          sampleCount:
            warmupData?.overall?.sampleCount ??
            warmupData?.symbols?.[Object.keys(warmupData?.symbols || {})[0]]?.sampleCount,
          minSamples:
            warmupData?.overall?.minSamples ??
            warmupData?.symbols?.[Object.keys(warmupData?.symbols || {})[0]]?.minSamples,
          candleCount:
            warmupData?.overall?.candleCount ??
            warmupData?.symbols?.[Object.keys(warmupData?.symbols || {})[0]]?.candleCount,
          minCandles:
            warmupData?.overall?.minCandles ??
            warmupData?.symbols?.[Object.keys(warmupData?.symbols || {})[0]]?.minCandles,
        }}
        errorMessage={startupModal.errorMessage}
        botName={startupModal.botName}
        tradingMode={startupModal.tradingMode}
        qualityMessage={dataQualityWarning || undefined}
      />
    </TooltipProvider>
  );
}

export default RunBar;
