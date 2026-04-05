import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { useActiveConfig, useBotInstances } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import {
  fetchRuntimeKnobs,
  fetchRuntimeConfigEffective,
  applyRuntimeConfig,
  fetchRuntimeConfigExport,
  importRuntimeConfigFromEnv,
  type RuntimeKnobSpec,
} from "../../lib/api/client";
import toast from "react-hot-toast";

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

function validateRuntimeConfig(knobs: RuntimeKnobSpec[], cfg: Record<string, any> | null): string[] {
  if (!cfg) return ["Config not loaded"];
  const errors: string[] = [];
  for (const knob of knobs) {
    const sectionValues = (cfg[knob.section] || {}) as Record<string, any>;
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
  const risk = (cfg.risk_config || {}) as Record<string, any>;
  const execution = (cfg.execution_config || {}) as Record<string, any>;
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

function collectFieldErrors(knobs: RuntimeKnobSpec[], cfg: Record<string, any> | null): Record<string, string> {
  if (!cfg) return {};
  const fieldErrors: Record<string, string> = {};
  for (const knob of knobs) {
    const sectionValues = (cfg[knob.section] || {}) as Record<string, any>;
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

export default function RuntimeConfigPage() {
  const { exchangeAccountId } = useScopeStore();
  const { data: activeConfigData } = useActiveConfig();
  const { data: botInstancesData } = useBotInstances();
  const allBots = (botInstancesData as any)?.bots || [];
  const botForExchange = allBots.find((bot: any) =>
    bot.exchangeConfigs?.some((config: any) => config.exchange_account_id === exchangeAccountId),
  );
  const exchangeConfigForScope =
    botForExchange?.exchangeConfigs?.find((config: any) => config.exchange_account_id === exchangeAccountId) || null;
  const botExchangeConfigId =
    exchangeConfigForScope?.id ||
    (activeConfigData as any)?.active?.id ||
    allBots?.[0]?.exchangeConfigs?.[0]?.id ||
    null;

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [knobs, setKnobs] = useState<RuntimeKnobSpec[]>([]);
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [enabledSymbols, setEnabledSymbols] = useState("");
  const [envSyncText, setEnvSyncText] = useState("");

  useEffect(() => {
    if (!botExchangeConfigId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchRuntimeKnobs(), fetchRuntimeConfigEffective(botExchangeConfigId)])
      .then(([knobRes, effective]) => {
        if (cancelled) return;
        setKnobs(knobRes.knobs || []);
        setConfig(effective.config as unknown as Record<string, any>);
        setEnabledSymbols((effective.config?.enabled_symbols || []).join(", "));
      })
      .catch((err: any) => toast.error(formatApiError(err, "Failed to load runtime config")))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [botExchangeConfigId]);

  const grouped = useMemo(() => {
    return {
      risk_config: knobs.filter((k) => k.section === "risk_config"),
      execution_config: knobs.filter((k) => k.section === "execution_config"),
      profile_overrides: knobs.filter((k) => k.section === "profile_overrides"),
    };
  }, [knobs]);

  const fieldErrors = useMemo(() => collectFieldErrors(knobs, config), [knobs, config]);
  const validationErrors = useMemo(() => validateRuntimeConfig(knobs, config), [knobs, config]);

  const setKnob = (knob: RuntimeKnobSpec, raw: string) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const next = { ...prev };
      const section = { ...(next[knob.section] || {}) };
      const writeKey = resolveWriteKey(section, knob.key);
      let val: unknown = raw;
      if (knob.type === "int") val = raw === "" ? null : parseInt(raw, 10);
      if (knob.type === "float") val = raw === "" ? null : parseFloat(raw);
      if (knob.type === "bool") val = raw === "true";
      section[writeKey] = val;
      next[knob.section] = section;
      return next;
    });
  };

  const onApply = async () => {
    if (!botExchangeConfigId || !config) return;
    if (validationErrors.length) {
      return;
    }
    setSaving(true);
    try {
      const symbols = enabledSymbols
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await applyRuntimeConfig({
        botExchangeConfigId,
        enabledSymbols: symbols,
        riskConfig: config.risk_config || {},
        executionConfig: config.execution_config || {},
        profileOverrides: config.profile_overrides || {},
      });
      setConfig(res.config as unknown as Record<string, any>);
      toast.success(`Applied runtime config v${res.config.config_version}`);
    } catch (err: any) {
      toast.error(formatApiError(err, "Apply failed"));
    } finally {
      setSaving(false);
    }
  };

  const onCopyEnvFromDb = async () => {
    if (!botExchangeConfigId) return;
    setSyncing(true);
    try {
      const res = await fetchRuntimeConfigExport(botExchangeConfigId);
      setEnvSyncText(res.env_text || "");
      await navigator.clipboard.writeText(res.env_text || "");
      toast.success(`Copied mapped .env (${Object.keys(res.runtime_env || {}).length} keys)`);
    } catch (err: any) {
      toast.error(formatApiError(err, "Failed to export mapped env"));
    } finally {
      setSyncing(false);
    }
  };

  const onImportEnvToDb = async (dryRun: boolean) => {
    if (!botExchangeConfigId || !envSyncText.trim()) return;
    setSyncing(true);
    try {
      const res = await importRuntimeConfigFromEnv({
        botExchangeConfigId,
        envText: envSyncText,
        dryRun,
        changeSummary: dryRun ? "runtime_env_import_dry_run" : "runtime_env_import",
      });
      if (dryRun) {
        const unmappedCount = (res.unmapped_env_keys || []).length;
        toast.success(`Dry run OK${unmappedCount ? ` (${unmappedCount} unmapped keys)` : ""}`);
        return;
      }
      if (res.config) {
        setConfig(res.config as unknown as Record<string, any>);
        setEnabledSymbols((res.config.enabled_symbols || []).join(", "));
      }
      const unmappedCount = (res.unmapped_env_keys || []).length;
      toast.success(`Imported to bot/exchange config${unmappedCount ? ` (${unmappedCount} unmapped keys)` : ""}`);
    } catch (err: any) {
      toast.error(`Import validation failed: ${formatApiError(err, "Failed to import env overrides")}`);
    } finally {
      setSyncing(false);
    }
  };

  if (!botExchangeConfigId) {
    return (
      <div className="p-6">
        <Card>
          <CardHeader>
            <CardTitle>Runtime Config</CardTitle>
            <CardDescription>
              No bot/exchange config is currently resolvable. Select a bot scope in the top scope selector, then refresh.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6">
      <Card>
        <CardHeader>
          <CardTitle>Runtime Config</CardTitle>
          <CardDescription>
            Golden source used at bot start. Changes create a new `config_version`.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded border p-3 space-y-2">
            <p className="text-sm font-semibold">DB/Config Sync</p>
            <p className="text-xs text-muted-foreground">
              Export mapped env values from current bot/exchange config, or paste env overrides and import them back.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" onClick={onCopyEnvFromDb} disabled={loading || syncing}>
                {syncing ? "Working..." : "Copy .env From DB"}
              </Button>
              <Button type="button" variant="outline" onClick={() => onImportEnvToDb(true)} disabled={loading || syncing || !envSyncText.trim()}>
                Dry Run Import
              </Button>
              <Button type="button" onClick={() => onImportEnvToDb(false)} disabled={loading || syncing || !envSyncText.trim()}>
                {"Apply Env -> Bot/Exchange"}
              </Button>
            </div>
            <textarea
              className="w-full min-h-[140px] rounded border bg-background px-3 py-2 text-xs font-mono"
              placeholder={"MAX_POSITIONS=3\nRISK_PER_TRADE_PCT=0.5\nORDERBOOK_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT"}
              value={envSyncText}
              onChange={(e) => setEnvSyncText(e.target.value)}
            />
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-1">Enabled Symbols</p>
            <Input value={enabledSymbols} onChange={(e) => setEnabledSymbols(e.target.value)} />
          </div>
          {(["risk_config", "execution_config", "profile_overrides"] as const).map((section) => (
            <div key={section} className="rounded border p-3 space-y-2">
              <p className="text-sm font-semibold">{section}</p>
              {section === "risk_config" && validationErrors.length > 0 && (
                <div className="rounded border border-red-500/40 bg-red-500/5 p-2 text-xs text-red-600 dark:text-red-400">
                  {validationErrors.map((error, idx) => (
                    <p key={`${error}-${idx}`}>{error}</p>
                  ))}
                </div>
              )}
              {grouped[section].map((knob) => {
                const sectionValues = (config?.[section] || {}) as Record<string, any>;
                const value = readKnobValue(sectionValues, knob.key);
                const displayValue =
                  value === undefined || value === null || value === "" ? (knob.default ?? "") : value;
                const fieldError = fieldErrors[`${section}.${knob.key}`];
                return (
                  <div
                    key={`${section}.${knob.key}`}
                    className="grid grid-cols-1 md:grid-cols-[minmax(240px,1fr)_minmax(220px,1fr)] gap-2 items-start"
                  >
                    <div className="text-sm min-w-0">
                      <p className="leading-5 break-words">{knob.label}</p>
                      <p className="text-[11px] text-muted-foreground font-mono break-all">
                        {section}.{knob.key}
                      </p>
                    </div>
                    <div className="min-w-0">
                      {knob.type === "bool" ? (
                        <select
                          className="w-full rounded border bg-background px-2 py-1 text-sm"
                          value={displayValue === true ? "true" : "false"}
                          onChange={(e) => setKnob(knob, e.target.value)}
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
                          onChange={(e) => setKnob(knob, e.target.value)}
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
          ))}
          <Button onClick={onApply} disabled={loading || saving || validationErrors.length > 0}>
            {saving ? "Applying..." : "Apply Runtime Config"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
