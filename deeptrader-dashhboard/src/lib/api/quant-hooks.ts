/**
 * Quant-grade infrastructure API hooks
 * Provides React Query hooks for kill switch, config bundles, reconciliation, and latency metrics.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useScopeStore } from "../../store/scope-store";

// ═══════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════

export interface KillSwitchState {
  is_active: boolean;
  triggered_by: Record<string, number>;
  message: string;
  last_reset_ts: number | null;
  last_reset_by: string | null;
}

export interface KillSwitchStatusResponse {
  success: boolean;
  status: {
    is_active: boolean;
    triggered_by: Record<string, number>;
    message: string;
    last_reset_ts: number | null;
    last_reset_by: string | null;
    blocks_count: number;
  };
}

export interface KillSwitchHistory {
  type: "trigger" | "reset";
  trigger?: string;
  message?: string;
  operator_id?: string;
  timestamp: number;
}

export interface ConfigBundle {
  id: string;
  version: number;
  tenant_id: string;
  bot_id: string;
  status: "draft" | "pending_review" | "approved" | "rejected" | "active" | "rolled_back";
  features_hash: string | null;
  model_hash: string | null;
  calibrator_hash: string | null;
  risk_params: Record<string, unknown>;
  execution_params: Record<string, unknown>;
  created_at: string;
  created_by: string | null;
  approved_at: string | null;
  approved_by: string | null;
  activated_at: string | null;
  rollback_target_id: string | null;
  notes: string | null;
}

export interface ReconciliationStatus {
  last_run_at: number | null;
  next_run_in_seconds: number | null;
  total_runs: number;
  discrepancies_found: number;
  discrepancies_healed: number;
  is_running: boolean;
}

export interface Discrepancy {
  type: string;
  symbol: string;
  local_state: Record<string, unknown>;
  exchange_state: Record<string, unknown>;
  healed: boolean;
  timestamp: number;
}

export interface LatencyMetrics {
  [key: string]: {
    p50: number;
    p95: number;
    p99: number;
    max: number;
    count: number;
  };
}

// ═══════════════════════════════════════════════════════════════
// KILL SWITCH API
// ═══════════════════════════════════════════════════════════════

export const fetchKillSwitchStatus = (botId?: string | null) =>
  api
    .get<KillSwitchStatusResponse>("/quant/kill-switch/status", {
      params: botId ? { bot_id: botId } : undefined,
    })
    .then((res) => res.data);

export const triggerKillSwitch = (data: { trigger: string; message?: string }, botId?: string | null) =>
  api
    .post<{ success: boolean; message: string }>("/quant/kill-switch/trigger", data, {
      params: botId ? { bot_id: botId } : undefined,
    })
    .then((res) => res.data);

export const resetKillSwitch = (operator_id?: string, botId?: string | null) =>
  api
    .post<{ success: boolean; message: string }>(
      "/quant/kill-switch/reset",
      { operator_id },
      { params: botId ? { bot_id: botId } : undefined },
    )
    .then((res) => res.data);

export const fetchKillSwitchHistory = (limit?: number, botId?: string | null) =>
  api
    .get<{ success: boolean; history: KillSwitchHistory[] }>("/quant/kill-switch/history", {
      params: { limit, ...(botId ? { bot_id: botId } : {}) },
    })
    .then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// CONFIG BUNDLES API
// ═══════════════════════════════════════════════════════════════

export const fetchConfigBundles = (status?: string) =>
  api.get<{ success: boolean; bundles: ConfigBundle[] }>("/quant/config/bundles", { params: { status } }).then((res) => res.data);

export const createConfigBundle = (data: {
  risk_params?: Record<string, unknown>;
  execution_params?: Record<string, unknown>;
  notes?: string;
}) =>
  api.post<{ success: boolean; bundle: ConfigBundle }>("/quant/config/bundles", data).then((res) => res.data);

export const submitBundleForReview = (bundleId: string) =>
  api.post<{ success: boolean; bundle: ConfigBundle }>(`/quant/config/bundles/${bundleId}/submit`).then((res) => res.data);

export const approveBundle = (bundleId: string) =>
  api.post<{ success: boolean; bundle: ConfigBundle }>(`/quant/config/bundles/${bundleId}/approve`).then((res) => res.data);

export const rejectBundle = (bundleId: string, reason?: string) =>
  api.post<{ success: boolean; bundle: ConfigBundle }>(`/quant/config/bundles/${bundleId}/reject`, { reason }).then((res) => res.data);

export const activateBundle = (bundleId: string) =>
  api.post<{ success: boolean; bundle: ConfigBundle }>(`/quant/config/bundles/${bundleId}/activate`).then((res) => res.data);

export const rollbackBundle = (bundleId: string, targetBundleId: string) =>
  api.post<{ success: boolean; bundle: ConfigBundle }>(`/quant/config/bundles/${bundleId}/rollback`, { target_bundle_id: targetBundleId }).then((res) => res.data);

export const fetchConfigAudit = (bundleId: string) =>
  api.get<{ success: boolean; audit: Array<{ action: string; actor: string; timestamp: string; details: Record<string, unknown> }> }>(`/quant/config/bundles/${bundleId}/audit`).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// RECONCILIATION API
// ═══════════════════════════════════════════════════════════════

export const fetchReconciliationStatus = () =>
  api.get<{ success: boolean; status: ReconciliationStatus }>("/quant/reconciliation/status").then((res) => res.data);

export const fetchReconciliationDiscrepancies = (limit?: number, healed?: boolean) =>
  api.get<{ success: boolean; discrepancies: Discrepancy[] }>("/quant/reconciliation/discrepancies", { params: { limit, healed } }).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// LATENCY METRICS API
// ═══════════════════════════════════════════════════════════════

export const fetchLatencyMetrics = () =>
  api.get<{ success: boolean; metrics: LatencyMetrics }>("/quant/metrics/latency").then((res) => res.data);

export interface LatencyHistoryPoint {
  timestamp: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  count: number;
}

export interface LatencyHistoryResponse {
  operation: string | null;
  history: LatencyHistoryPoint[];
  operations: string[];
  hours: number;
}

export const fetchLatencyHistory = (operation?: string, hours = 1) =>
  api
    .get<LatencyHistoryResponse>("/quant/latency/history", {
      params: { operation, hours },
    })
    .then((res) => res.data);

export const fetchLatencyOperations = () =>
  api
    .get<{ operations: Array<{ name: string; p50_ms: number; p95_ms: number; p99_ms: number; count: number }> }>(
      "/quant/latency/operations"
    )
    .then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// SAFETY EVENTS API
// ═══════════════════════════════════════════════════════════════

export interface SafetyEvent {
  type: "kill_switch" | "guard";
  subtype: string;
  timestamp: number;
  message: string;
  symbol?: string;
  side?: string;
  realized_pnl?: number;
  trigger?: string;
  operator_id?: string;
}

export const fetchSafetyEvents = (limit = 50) =>
  api.get<{ events: SafetyEvent[] }>("/quant/safety-events", { params: { limit } }).then((res) => res.data);

export const fetchGuardEvents = (limit = 50) =>
  api.get<{ events: Array<Record<string, unknown>> }>("/quant/guard-events", { params: { limit } }).then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// CORRELATION GUARD API
// ═══════════════════════════════════════════════════════════════

export const fetchCorrelationGuardStats = () =>
  api.get<{ checks_total: number; blocks_total: number; block_rate: number }>("/quant/correlation-guard/stats").then((res) => res.data);

export const fetchCorrelationMatrix = () =>
  api.get<{ correlations: Record<string, number> }>("/quant/correlation-guard/matrix").then((res) => res.data);

// ═══════════════════════════════════════════════════════════════
// REACT QUERY HOOKS
// ═══════════════════════════════════════════════════════════════

export function useKillSwitchStatus() {
  const scopeBotId = useScopeStore((s) => s.botId);
  return useQuery({
    queryKey: ["quant", "killSwitch", "status", scopeBotId],
    queryFn: () => fetchKillSwitchStatus(scopeBotId),
    refetchInterval: 5000, // Poll every 5 seconds
    staleTime: 2000,
    enabled: !!scopeBotId,
  });
}

export function useKillSwitchHistory(limit = 50) {
  const scopeBotId = useScopeStore((s) => s.botId);
  return useQuery({
    queryKey: ["quant", "killSwitch", "history", limit, scopeBotId],
    queryFn: () => fetchKillSwitchHistory(limit, scopeBotId),
    staleTime: 10000,
    enabled: !!scopeBotId,
  });
}

export function useTriggerKillSwitch() {
  const scopeBotId = useScopeStore((s) => s.botId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { trigger: string; message?: string }) => {
      if (!scopeBotId) return Promise.reject(new Error("bot_id_required"));
      return triggerKillSwitch(data, scopeBotId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quant", "killSwitch"] });
    },
  });
}

export function useResetKillSwitch() {
  const scopeBotId = useScopeStore((s) => s.botId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (operator_id?: string) => {
      if (!scopeBotId) return Promise.reject(new Error("bot_id_required"));
      return resetKillSwitch(operator_id, scopeBotId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quant", "killSwitch"] });
    },
  });
}

export function useConfigBundles(status?: string) {
  return useQuery({
    queryKey: ["quant", "configBundles", status],
    queryFn: () => fetchConfigBundles(status),
    staleTime: 30000,
  });
}

export function useReconciliationStatus() {
  return useQuery({
    queryKey: ["quant", "reconciliation", "status"],
    queryFn: fetchReconciliationStatus,
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

export function useReconciliationDiscrepancies(limit = 100, healed?: boolean) {
  return useQuery({
    queryKey: ["quant", "reconciliation", "discrepancies", limit, healed],
    queryFn: () => fetchReconciliationDiscrepancies(limit, healed),
    staleTime: 30000,
  });
}

export function useLatencyMetrics() {
  return useQuery({
    queryKey: ["quant", "latency"],
    queryFn: fetchLatencyMetrics,
    refetchInterval: 10000,
    staleTime: 5000,
  });
}

export function useLatencyHistory(operation?: string, hours = 1) {
  return useQuery({
    queryKey: ["quant", "latency", "history", operation, hours],
    queryFn: () => fetchLatencyHistory(operation, hours),
    refetchInterval: 60000, // Refresh every minute
    staleTime: 30000,
  });
}

export function useLatencyOperations() {
  return useQuery({
    queryKey: ["quant", "latency", "operations"],
    queryFn: fetchLatencyOperations,
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

export function useSafetyEvents(limit = 50) {
  return useQuery({
    queryKey: ["quant", "safetyEvents", limit],
    queryFn: () => fetchSafetyEvents(limit),
    refetchInterval: 5000, // Refresh every 5 seconds
    staleTime: 2000,
  });
}

export function useGuardEvents(limit = 50) {
  return useQuery({
    queryKey: ["quant", "guardEvents", limit],
    queryFn: () => fetchGuardEvents(limit),
    refetchInterval: 5000,
    staleTime: 2000,
  });
}

export function useCorrelationGuardStats() {
  return useQuery({
    queryKey: ["quant", "correlationGuard", "stats"],
    queryFn: fetchCorrelationGuardStats,
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

export function useCorrelationMatrix() {
  return useQuery({
    queryKey: ["quant", "correlationGuard", "matrix"],
    queryFn: fetchCorrelationMatrix,
    staleTime: 60000 * 5, // Cache for 5 minutes (static data)
  });
}

// ═══════════════════════════════════════════════════════════════
// PIPELINE HEALTH API
// ═══════════════════════════════════════════════════════════════

export interface WorkerHealth {
  name: string;
  status: "healthy" | "degraded" | "down" | "idle";
  latency_p99_ms: number;
  throughput_per_sec: number;
  last_event_ts: number | null;
  error_message: string | null;
  mds_quality_score?: number | null;
  orderbook_event_rate_l1_eps?: number | null;
  orderbook_event_rate_l2_eps?: number | null;
}

export interface SymbolStatus {
  symbol: string;
  status: "healthy" | "degraded" | "down" | "idle";
  last_decision_ts: number | null;
  age_sec: number | null;
  rejection_reason: string | null;
  profile_id: string | null;
  strategy_id?: string | null;
  session?: string | null;
  decisions_count?: number;
}

export interface LayerHealth {
  name: string;
  display_name: string;
  status: "healthy" | "degraded" | "down" | "idle";
  latency_p50_ms: number;
  latency_p95_ms: number;
  latency_p99_ms: number;
  throughput_per_sec: number;
  last_event_ts: number | null;
  age_sec: number | null;
  blockers: string[];
  workers: WorkerHealth[];
  events_processed: number;
  events_rejected: number;
  symbol_status?: SymbolStatus[];  // Per-symbol status for decision layer
}

export interface PipelineHealthResponse {
  layers: LayerHealth[];
  overall_status: "healthy" | "degraded" | "down";
  tick_to_execution_p99_ms: number;
  decisions_per_minute: number;
  fills_per_hour: number;
  kill_switch_active: boolean;
  prediction?: {
    mode: "onnx" | "onnx_moe" | "fallback" | "mixed" | "unknown";
    onnx_status: "active" | "partial" | "blocked" | "unknown";
    live_primary_source: string;
    live_source_counts: Record<string, number>;
    shadow_source_counts: Record<string, number>;
    gate_status_counts: Record<string, number>;
    onnx_live_share_pct: number;
    fallback_rate_pct: number;
    score_gate_mode: string;
    score_snapshot_provider: string;
    score_snapshot_status: string;
    score_snapshot_age_sec: number | null;
    moe_enabled: boolean;
    moe_experts_total: number;
    moe_experts_with_calibration: number;
    moe_latest_calibration_age_sec: number | null;
    moe_model_meta_path: string | null;
    moe_expert_status: Array<{
      id: string;
      calibration_source: string;
      calibrated_classes: number;
      fitted_at: number | null;
      age_sec: number | null;
    }>;
    symbols: Array<{
      symbol: string;
      status: string;
      samples: number;
      ml_score: number | null;
      exact_accuracy: number | null;
      ece_top1: number | null;
    }>;
    directional_canary?: {
      samples_close_fills: number;
      long: {
        trades: number;
        pnl_samples: number;
        win_rate: number | null;
        expectancy_net_pnl: number | null;
      };
      short: {
        trades: number;
        pnl_samples: number;
        win_rate: number | null;
        expectancy_net_pnl: number | null;
      };
    };
    rolling_performance?: Record<
      string,
      {
        window_hours: number;
        total: {
          n: number;
          wins: number;
          sum_net_pnl: number;
          avg_net_pnl: number | null;
          win_rate: number | null;
        };
        by_source: Record<
          string,
          {
            n: number;
            wins: number;
            sum_net_pnl: number;
            avg_net_pnl: number | null;
            win_rate: number | null;
          }
        >;
        by_source_side?: Record<
          string,
          Record<
            string,
            {
              n: number;
              wins: number;
              sum_net_pnl: number;
              avg_net_pnl: number | null;
              win_rate: number | null;
            }
          >
        >;
      }
    >;
    entry_quality_readiness?: {
      sample_count: number;
      decision_sample_count: number;
      readiness_counts: Record<string, number>;
      gate_status_counts: Record<string, number>;
      green_pct: number;
      blocked_pct: number;
      fallback_pct: number;
      checks: Array<{
        name: string;
        actual: number;
        target?: number;
        target_max?: number;
        passed: boolean;
      }>;
      blockers: string[];
      ready: boolean;
      recommendation: string;
      top_blocking_reasons: Array<{
        reason: string;
        count: number;
      }>;
      thresholds: {
        min_green_pct: number;
        max_blocked_pct: number;
        max_fallback_pct: number;
      };
    };
    input_feature_health?: {
      status: "ok" | "warning" | "critical" | string;
      sample_count: number;
      feature_count: number;
      source_counts?: {
        onnx?: number;
        heuristic?: number;
        other?: number;
      };
      critical_features?: string[];
      warning_features?: string[];
      features?: Array<{
        name: string;
        status: "ok" | "warning" | "critical" | string;
        samples: number;
        missing_pct: number;
        fallback_from_market_context_pct: number;
        zero_pct: number;
        unique_values: number;
        p01: number | null;
        p99: number | null;
        range_p01_p99: number | null;
        stddev: number;
      }>;
    };
  };
  timestamp: number;
}

export const fetchPipelineHealth = (botId?: string | null) =>
  api
    .get<PipelineHealthResponse>("/quant/pipeline/health", {
      params: botId ? { bot_id: botId } : undefined,
    })
    .then((res) => res.data);

export function usePipelineHealth(refetchInterval = 5000) {
  const scopeBotId = useScopeStore((s) => s.botId);
  return useQuery({
    queryKey: ["quant", "pipeline", "health", scopeBotId],
    queryFn: () => fetchPipelineHealth(scopeBotId),
    refetchInterval,
    staleTime: 2000,
    enabled: !!scopeBotId,
  });
}
