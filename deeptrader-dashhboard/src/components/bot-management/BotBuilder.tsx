/**
 * BotBuilder - Wizard for creating and editing bots
 * 
 * Multi-step wizard with:
 * - Start (blank, template, clone)
 * - Identity (name, role, template)
 * - Exchange (account, environment)
 * - Capital (trading capital, position size, leverage)
 * - Advanced (risk limits, execution settings)
 * - Symbols (enabled symbols, overrides)
 * - Review (final confirmation)
 */

import { useState, useMemo, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import {
  Bot,
  Check,
  ChevronRight,
  Copy,
  DollarSign,
  Layers,
  Loader2,
  Lock,
  Pencil,
  PieChart,
  Plus,
  Server,
  Settings,
  Shield,
  Sparkles,
  Wallet,
  Zap,
  ArrowRight,
  AlertCircle,
  AlertTriangle,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Badge } from "../ui/badge";
import { Textarea } from "../ui/textarea";
import { Separator } from "../ui/separator";
import { Checkbox } from "../ui/checkbox";
import { Select } from "../ui/select";
import { Switch } from "../ui/switch";

import {
  useBotInstances,
  useCreateBotInstance,
  useActivateBotExchangeConfig,
  useStrategyTemplates,
  useTenantRiskPolicy,
  useUpdateBotSymbolConfig,
  useUpdateBotInstance,
  useCreateBotExchangeConfig,
} from "../../lib/api/hooks";
import { useExchangeAccounts } from "../../lib/api/exchange-accounts-hooks";
import type { BotEnvironment, BotInstance, BotExchangeConfig, AllocatorRole } from "../../lib/api/types";

import {
  ENVIRONMENTS,
  ALLOCATOR_ROLES,
  SYMBOL_OPTIONS,
  THROTTLE_MODES,
  MARKET_TYPES,
  BOT_TYPES,
  SPOT_RISK_DEFAULTS,
  SPOT_EXECUTION_DEFAULTS,
  getEnvironmentBadge,
  getRoleBadge,
  getMarketTypeLabel,
  getMarketTypeBadge,
  getSymbolsForMarketType,
  getQuickAddSymbols,
  formatCurrency,
} from "./types";
import type { ExchangeAccountOption, WizardStep, ThrottleMode } from "./types";
import type { BotKind } from "./types";

// ═══════════════════════════════════════════════════════════════
// HELPER COMPONENTS
// ═══════════════════════════════════════════════════════════════

interface StartOptionCardProps {
  selected: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  description: string;
  badge?: string;
  disabled?: boolean;
  disabledReason?: string;
}

function StartOptionCard({ 
  selected, 
  onClick, 
  icon, 
  title, 
  description, 
  badge, 
  disabled, 
  disabledReason 
}: StartOptionCardProps) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={`relative rounded-xl border p-6 text-left transition-all ${
        disabled
          ? "border-border/50 bg-muted/20 opacity-60 cursor-not-allowed"
          : selected
          ? "border-primary bg-primary/10 shadow-lg"
          : "border-border hover:border-primary/50 hover:bg-muted/30"
      }`}
    >
      {badge && (
        <Badge className={`absolute top-3 right-3 text-[10px] ${
          disabled ? "bg-muted text-muted-foreground" : "bg-primary"
        }`}>
          {badge}
        </Badge>
      )}
      <div className={`mb-4 ${
        disabled ? "text-muted-foreground/50" : selected ? "text-primary" : "text-muted-foreground"
      }`}>
        {icon}
      </div>
      <h3 className={`font-semibold mb-1 ${disabled && "text-muted-foreground"}`}>{title}</h3>
      <p className="text-sm text-muted-foreground">{description}</p>
      {disabled && disabledReason && (
        <p className="text-xs text-amber-500 mt-2 flex items-center gap-1">
          <AlertCircle className="h-3 w-3" />
          {disabledReason}
        </p>
      )}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════

interface BotBuilderProps {
  editingBot: BotInstance | null;
  onCancel: () => void;
  onComplete: () => void;
}

export function BotBuilder({ editingBot, onCancel, onComplete }: BotBuilderProps) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<WizardStep>(editingBot ? "identity" : "start");
  const [startMode, setStartMode] = useState<"blank" | "template" | "clone">("blank");

  // Form state - Identity
  const [name, setName] = useState(editingBot?.name || "");
  const [description, setDescription] = useState(editingBot?.description || "");
  const [allocatorRole, setAllocatorRole] = useState<string>(editingBot?.allocator_role || "core");
  const [templateId, setTemplateId] = useState(editingBot?.strategy_template_id || "");
  const [marketType, setMarketType] = useState<"perp" | "spot">((editingBot as any)?.market_type || "perp");
  const [botType, setBotType] = useState<BotKind>(((editingBot as any)?.bot_type || "standard") as BotKind);
  
  // Form state - Exchange
  const [credentialId, setCredentialId] = useState("");
  const [environment, setEnvironment] = useState<BotEnvironment>("paper");
  // Trading mode: "live" for testnet/live accounts, "paper" for paper simulation
  const [tradingMode, setTradingMode] = useState<"paper" | "live">("paper");
  
  // Form state - Capital
  const [tradingCapital, setTradingCapital] = useState<number | "">("");
  const [positionSizePct, setPositionSizePct] = useState<number | "">(5);
  const [maxLeverage, setMaxLeverage] = useState<number | "">(3);
  const [minPositionSizeUsd, setMinPositionSizeUsd] = useState<number>(10);
  const [maxPositionSizeUsd, setMaxPositionSizeUsd] = useState<number>(0);
  
  // Form state - Advanced Risk
  const [maxPositions, setMaxPositions] = useState<number>(4);
  const [maxPositionsPerStrategy, setMaxPositionsPerStrategy] = useState<number>(0);
  const [leverageMode, setLeverageMode] = useState<"isolated" | "cross">("isolated");
  const [maxDailyLossPct, setMaxDailyLossPct] = useState<number>(5);
  const [maxTotalExposurePct, setMaxTotalExposurePct] = useState<number>(80);
  const [maxExposurePerSymbolPct, setMaxExposurePerSymbolPct] = useState<number>(25);
  const [maxPositionsPerSymbol, setMaxPositionsPerSymbol] = useState<number>(1);
  const [maxDailyLossPerSymbolPct, setMaxDailyLossPerSymbolPct] = useState<number>(2.5);
  const [maxDrawdownPct, setMaxDrawdownPct] = useState<number>(10);
  
  // Form state - Advanced Execution
  const [defaultOrderType, setDefaultOrderType] = useState<"market" | "limit">("market");
  const [stopLossPct, setStopLossPct] = useState<number>(2);
  const [takeProfitPct, setTakeProfitPct] = useState<number>(5);
  const [trailingStopEnabled, setTrailingStopEnabled] = useState<boolean>(false);
  const [trailingStopPct, setTrailingStopPct] = useState<number>(1);
  const [maxHoldTimeHours, setMaxHoldTimeHours] = useState<number>(24);
  const [minTradeIntervalSec, setMinTradeIntervalSec] = useState<number>(1);
  const [executionTimeoutSec, setExecutionTimeoutSec] = useState<number>(5);
  const [enableVolatilityFilter, setEnableVolatilityFilter] = useState<boolean>(true);
  const [throttleMode, setThrottleMode] = useState<ThrottleMode>("swing");
  const [orderIntentMaxAgeSec, setOrderIntentMaxAgeSec] = useState<number>(0);
  const [aiShadowMode, setAiShadowMode] = useState<boolean>(true);
  const [aiConfidenceFloor, setAiConfidenceFloor] = useState<number>(0.74);
  const [aiSentimentRequired, setAiSentimentRequired] = useState<boolean>(true);
  const [aiRequireBaselineAlignment, setAiRequireBaselineAlignment] = useState<boolean>(true);
  const [aiSessions, setAiSessions] = useState<string[]>(["london", "ny"]);
  
  // Form state - Symbols
  const [enabledSymbols, setEnabledSymbols] = useState<string[]>(["BTC-USDT-SWAP"]);
  const [symbolOverrides, setSymbolOverrides] = useState<Record<string, { minNotionalUsd?: number; maxLeverage?: number }>>({});
  const [notes, setNotes] = useState("");
  const [activate, setActivate] = useState(true);

  // API Hooks
  const { data: templatesData } = useStrategyTemplates();
  const { data: policyData } = useTenantRiskPolicy();
  const { data: exchangeAccountsData, isLoading: isLoadingExchangeAccounts } = useExchangeAccounts();
  const { data: botsData } = useBotInstances();
  
  const createBotMutation = useCreateBotInstance();
  const createConfigMutation = useCreateBotExchangeConfig();
  const activateMutation = useActivateBotExchangeConfig();
  const updateSymbolMutation = useUpdateBotSymbolConfig();
  const updateBotMutation = useUpdateBotInstance();

  // Derived state
  const exchangeAccounts = useMemo(() => {
    return (exchangeAccountsData || []) as ExchangeAccountOption[];
  }, [exchangeAccountsData]);

const verifiedAccounts = exchangeAccounts.filter((a) => a.status === "verified");
const selectedAccount = verifiedAccounts.find((a) => a.id === credentialId);

// Auto-select the only verified account to prevent empty configs
useEffect(() => {
    if (!credentialId && verifiedAccounts.length === 1) {
      setCredentialId(verifiedAccounts[0].id);
      setEnvironment((verifiedAccounts[0].environment as BotEnvironment) || "paper");
    }
}, [credentialId, verifiedAccounts]);

// Update tradingMode based on selected account and environment
useEffect(() => {
    if (selectedAccount) {
      // Paper accounts always use paper trading mode
      // Live/testnet accounts use live trading mode (real orders, even if on testnet)
      if (selectedAccount.environment === "paper") {
        setTradingMode("paper");
      } else {
        // For live or testnet accounts, use the selected environment
        setTradingMode(environment === "paper" ? "paper" : "live");
      }
    }
}, [selectedAccount, environment]);

// Check if editing an existing bot with exchange configs (environment is locked)
const existingConfig = editingBot?.exchangeConfigs?.[0];
const isEnvironmentLocked = !!existingConfig;

// Hydrate account/environment when editing an existing bot
useEffect(() => {
  if (existingConfig) {
    if (existingConfig.exchange_account_id && !credentialId) {
      setCredentialId(existingConfig.exchange_account_id);
    }
    if (existingConfig.environment) {
      setEnvironment(existingConfig.environment as BotEnvironment);
    }
  }
}, [existingConfig, credentialId, environment]);

useEffect(() => {
  if (botType !== "ai_spot_swing") return;
  setMarketType("spot");
  setMaxLeverage(1);
  setDefaultOrderType("limit");
  setStopLossPct(SPOT_EXECUTION_DEFAULTS.stopLossPct);
  setTakeProfitPct(SPOT_EXECUTION_DEFAULTS.takeProfitPct);
  setTrailingStopEnabled(true);
  setTrailingStopPct(SPOT_EXECUTION_DEFAULTS.trailingStopPct);
  setMaxHoldTimeHours(SPOT_EXECUTION_DEFAULTS.maxHoldTimeHours);
  setThrottleMode("conservative");
  setMaxPositions(SPOT_RISK_DEFAULTS.maxPositions);
  setMaxPositionsPerSymbol(SPOT_RISK_DEFAULTS.maxPositionsPerSymbol);
  setEnabledSymbols((current) => current.filter((symbol) => !symbol.includes("SWAP")).length ? current.filter((symbol) => !symbol.includes("SWAP")) : ["BTCUSDT"]);
}, [botType]);
  
  // Allow all environments (paper, live, dev) - testnet credentials can be used with live mode
  // for testing the live trading flow without real money at risk
  const allowedEnvironments = ENVIRONMENTS.filter((e) => e.value !== "all");

  // Multi-bot budget tracking
  const budgetInfo = useMemo(() => {
    if (!selectedAccount || !botsData?.bots) {
      return { 
        allocatedToOthers: 0, 
        otherBotCount: 0, 
        currentBotAllocation: 0,
        totalAllocated: 0,
        remainingAllocatable: undefined,
        isOverAllocated: false,
        overAllocationAmount: 0,
      };
    }

    const availableBalance = selectedAccount.available_balance !== undefined 
      ? Number(selectedAccount.available_balance) 
      : undefined;
    let allocatedToOthers = 0;
    let otherBotCount = 0;
    let currentBotAllocation = 0;

    botsData.bots.forEach((bot: BotInstance) => {
      bot.exchangeConfigs?.forEach((config: BotExchangeConfig) => {
        const matchesExchange = config.exchange_account_id === selectedAccount.id ||
          config.credential_id === selectedAccount.id;
        
        if (matchesExchange && config.trading_capital_usd) {
          const capital = Number(config.trading_capital_usd) || 0;
          
          if (editingBot && bot.id === editingBot.id) {
            currentBotAllocation = capital;
          } else {
            allocatedToOthers += capital;
            otherBotCount++;
          }
        }
      });
    });

    const totalAllocated = allocatedToOthers + currentBotAllocation;
    const isOverAllocated = availableBalance !== undefined && totalAllocated > availableBalance;
    const overAllocationAmount = isOverAllocated ? totalAllocated - (availableBalance || 0) : 0;
    const remainingAllocatable = availableBalance !== undefined 
      ? Math.max(0, availableBalance - allocatedToOthers)
      : undefined;

    return { 
      allocatedToOthers, 
      otherBotCount, 
      currentBotAllocation,
      totalAllocated,
      remainingAllocatable,
      isOverAllocated,
      overAllocationAmount,
    };
  }, [selectedAccount, botsData, editingBot, environment]);

  // Preview calculations
  const previewMaxExposure = typeof tradingCapital === "number" && typeof maxLeverage === "number"
    ? tradingCapital * maxLeverage
    : 0;
  const previewTradeSize = typeof tradingCapital === "number" && typeof positionSizePct === "number"
    ? (tradingCapital * positionSizePct) / 100
    : 0;

  // Step definitions
  const steps: { key: WizardStep; label: string; icon: React.ReactNode }[] = [
    { key: "start", label: "Start", icon: <Sparkles className="h-4 w-4" /> },
    { key: "identity", label: "Identity", icon: <Bot className="h-4 w-4" /> },
    { key: "exchange", label: "Exchange", icon: <Server className="h-4 w-4" /> },
    { key: "capital", label: "Capital", icon: <DollarSign className="h-4 w-4" /> },
    { key: "advanced", label: "Advanced", icon: <Settings className="h-4 w-4" /> },
    { key: "symbols", label: "Symbols", icon: <Layers className="h-4 w-4" /> },
    { key: "review", label: "Review", icon: <Check className="h-4 w-4" /> },
  ];

  const currentStepIndex = steps.findIndex((s) => s.key === step);
  const canGoBack = currentStepIndex > 0;
  const isLastStep = step === "review";

  // Validation
  const validateStep = (): boolean => {
    switch (step) {
      case "start":
        return true;
      case "identity":
        if (!name.trim()) {
          toast.error("Bot name is required");
          return false;
        }
        return true;
      case "exchange":
        if (!credentialId) {
          toast.error("Select a verified credential");
          return false;
        }
        return true;
      case "capital":
        if (!tradingCapital || tradingCapital <= 0) {
          toast.error("Trading capital must be > 0");
          return false;
        }
        if (!positionSizePct || positionSizePct <= 0) {
          toast.error("Position size % must be > 0");
          return false;
        }
        if (budgetInfo.remainingAllocatable !== undefined && typeof tradingCapital === 'number') {
          const isWithinBudget = tradingCapital <= budgetInfo.remainingAllocatable;
          const isReducingOrSame = !!editingBot && tradingCapital <= budgetInfo.currentBotAllocation;
          
          if (!isWithinBudget && !isReducingOrSame) {
            const overBy = tradingCapital - budgetInfo.remainingAllocatable;
            toast.error(`Trading capital exceeds remaining budget by $${overBy.toLocaleString()}`);
            return false;
          }
        }
        return true;
      case "advanced":
        if (maxPositions < 1) {
          toast.error("Max positions must be at least 1");
          return false;
        }
        if (stopLossPct <= 0 || stopLossPct > 50) {
          toast.error("Stop loss must be between 0.1% and 50%");
          return false;
        }
        return true;
      case "symbols":
        if (enabledSymbols.length === 0) {
          toast.error("Enable at least one symbol");
          return false;
        }
        return true;
      default:
        return true;
    }
  };

  const nextStep = () => {
    if (!validateStep()) return;
    const nextIndex = currentStepIndex + 1;
    if (nextIndex < steps.length) {
      setStep(steps[nextIndex].key);
    }
  };

  const prevStep = () => {
    const prevIndex = currentStepIndex - 1;
    if (prevIndex >= 0) {
      setStep(steps[prevIndex].key);
    }
  };

  const handleSubmit = async () => {
    try {
      if (!credentialId) {
        toast.error("Select an exchange account for this bot");
        setStep("exchange");
        return;
      }
      let botId = editingBot?.id;

      const fullRiskConfig = {
        positionSizePct: typeof positionSizePct === "number" ? positionSizePct : Number(positionSizePct),
        minPositionSizeUsd: minPositionSizeUsd,
        maxPositionSizeUsd: maxPositionSizeUsd,
        maxPositions,
        maxPositionsPerStrategy,
        maxDailyLossPct,
        maxTotalExposurePct,
        maxExposurePerSymbolPct,
        maxLeverage: typeof maxLeverage === "number" ? maxLeverage : Number(maxLeverage),
        leverageMode,
        maxPositionsPerSymbol,
        maxDailyLossPerSymbolPct,
        maxDrawdownPct,
      };

      const fullExecutionConfig = {
        defaultOrderType,
        stopLossPct,
        takeProfitPct,
        trailingStopEnabled,
        trailingStopPct,
        maxHoldTimeHours,
        minTradeIntervalSec,
        executionTimeoutSec,
        enableVolatilityFilter,
        throttleMode,
        orderIntentMaxAgeSec,
      };
      const profileOverrides = botType === "ai_spot_swing"
        ? {
            bot_type: "ai_spot_swing",
            ai_provider: "deepseek_context",
            ai_profile: "spot_ai_assist",
            ai_shadow_mode: aiShadowMode,
            ai_confidence_floor: aiConfidenceFloor,
            ai_sentiment_required: aiSentimentRequired,
            ai_require_baseline_alignment: aiRequireBaselineAlignment,
            ai_sessions: aiSessions,
          }
        : { bot_type: "standard" };

      if (editingBot) {
        await updateBotMutation.mutateAsync({
          botId: editingBot.id,
          data: {
            name: name.trim(),
            description: description.trim() || undefined,
            allocator_role: allocatorRole as AllocatorRole,
            strategy_template_id: templateId || undefined,
            bot_type: botType,
            default_risk_config: fullRiskConfig,
            default_execution_config: fullExecutionConfig,
            profile_overrides: profileOverrides,
          },
        });
      } else {
        const botRes = await createBotMutation.mutateAsync({
          name: name.trim(),
          description: description.trim() || undefined,
          strategyTemplateId: templateId || undefined,
          allocatorRole,
          botType,
          marketType,
          tradingMode,  // Include bot-level trading mode
          defaultRiskConfig: fullRiskConfig,
          defaultExecutionConfig: fullExecutionConfig,
          profileOverrides,
          aiProvider: "deepseek_context",
          aiProfile: "spot_ai_assist",
          aiShadowMode,
          aiConfidenceFloor,
          aiSentimentRequired,
          aiRequireBaselineAlignment,
          aiSessions,
        });
        botId = botRes.bot.id;
      }

      const configRes = await createConfigMutation.mutateAsync({
        botId: botId!,
        data: {
          exchangeAccountId: credentialId,
          exchange: selectedAccount?.venue,
          environment,
          tradingCapitalUsd: typeof tradingCapital === "number" ? tradingCapital : Number(tradingCapital),
          enabledSymbols,
          riskConfig: fullRiskConfig,
          executionConfig: fullExecutionConfig,
          profileOverrides,
          notes: notes || undefined,
        },
      });

      // Apply per-symbol overrides
      const symbolEntries = Object.entries(symbolOverrides).filter(([, v]) => v.minNotionalUsd || v.maxLeverage);
      for (const [symbol, overrides] of symbolEntries) {
        await updateSymbolMutation.mutateAsync({
          botId: botId!,
          configId: configRes.config.id,
          symbol,
          data: {
            max_leverage: overrides.maxLeverage,
            metadata: overrides.minNotionalUsd ? { minNotionalUsd: overrides.minNotionalUsd } : undefined,
          },
        });
      }

      if (activate) {
        await activateMutation.mutateAsync({ botId: botId!, configId: configRes.config.id });
      }

      toast.success(editingBot ? "Bot updated successfully" : "Bot created and activated");
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
      onComplete();
    } catch (error: any) {
      console.error(error);
      const apiMsg = error?.response?.data?.errors?.length
        ? error.response.data.errors.join("; ")
        : error?.response?.data?.message;
      toast.error(apiMsg || error?.message || "Failed to create bot");
    }
  };

  const isPending = createBotMutation.isPending || createConfigMutation.isPending || activateMutation.isPending;

  return (
    <div className="w-full">
      {/* Edit Mode Banner */}
      {editingBot && (
        <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 flex items-center gap-3">
          <div className="rounded-lg bg-amber-500/20 p-2">
            <Pencil className="h-5 w-5 text-amber-400" />
          </div>
          <div className="flex-1">
            <p className="font-medium text-amber-400">Edit Mode</p>
            <p className="text-sm text-muted-foreground">
              Editing <span className="font-semibold text-foreground">"{editingBot.name}"</span>
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onCancel} className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10">
            Cancel Edit
          </Button>
        </div>
      )}

      {/* Progress Steps */}
      <Card className="border-border/50 mb-6">
        <CardContent className="py-4">
          <div className="flex items-center justify-between">
            {steps.map((s, index) => {
              const isActive = s.key === step;
              const isCompleted = index < currentStepIndex;
              return (
                <div key={s.key} className="flex items-center">
                  <div
                    className={`flex items-center justify-center w-10 h-10 rounded-full border-2 transition-all ${
                      isActive
                        ? "border-primary bg-primary text-primary-foreground"
                        : isCompleted
                        ? "border-primary bg-primary/20 text-primary"
                        : "border-border bg-background text-muted-foreground"
                    }`}
                  >
                    {isCompleted ? <Check className="h-5 w-5" /> : s.icon}
                  </div>
                  <span className={`ml-2 text-sm hidden sm:inline ${isActive ? "font-medium" : "text-muted-foreground"}`}>
                    {s.label}
                  </span>
                  {index < steps.length - 1 && (
                    <ChevronRight className="mx-4 h-4 w-4 text-muted-foreground" />
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Step Content */}
      <Card className="border-border/50">
        <CardContent className="py-6">
          {/* START STEP */}
          {step === "start" && (
            <div className="space-y-6">
              <div className="text-center mb-8">
                <h2 className="text-2xl font-semibold mb-2">How would you like to start?</h2>
                <p className="text-muted-foreground">Choose a starting point for your new bot</p>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <StartOptionCard
                  selected={startMode === "blank"}
                  onClick={() => setStartMode("blank")}
                  icon={<Plus className="h-8 w-8" />}
                  title="Blank Bot"
                  description="Start from scratch with a custom configuration"
                />
                <StartOptionCard
                  selected={startMode === "template"}
                  onClick={() => setStartMode("template")}
                  icon={<Sparkles className="h-8 w-8" />}
                  title="From Template"
                  description="Use a pre-configured strategy template"
                  badge={templatesData?.templates?.length ? "Recommended" : undefined}
                  disabled={!templatesData?.templates?.length}
                  disabledReason={!templatesData?.templates?.length ? "No templates available" : undefined}
                />
                <StartOptionCard
                  selected={startMode === "clone"}
                  onClick={() => setStartMode("clone")}
                  icon={<Copy className="h-8 w-8" />}
                  title="Clone Existing"
                  description="Copy settings from an existing bot"
                  disabled={!botsData?.bots?.length}
                  disabledReason={!botsData?.bots?.length ? "No existing bots to clone" : undefined}
                />
              </div>

              {templatesData?.templates && templatesData.templates.length > 0 && (
                <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
                  <h4 className="font-medium text-sm mb-2 flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-primary" />
                    Available Templates ({templatesData.templates.length})
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {templatesData.templates.map((t) => (
                      <Badge key={t.id} variant="outline" className="text-xs">
                        {t.name}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* IDENTITY STEP */}
          {step === "identity" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold mb-1">Bot Identity</h2>
                <p className="text-muted-foreground text-sm">Define your bot's name, market type, and strategy</p>
              </div>

              <div className="space-y-2">
                <Label>Bot Type *</Label>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {BOT_TYPES.map((type) => (
                    <button
                      key={type.value}
                      onClick={() => setBotType(type.value)}
                      className={`rounded-xl border-2 p-4 text-left transition-all ${
                        botType === type.value
                          ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                          : "border-border hover:border-primary/50"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        {type.value === "ai_spot_swing" ? <Sparkles className="h-5 w-5 text-primary" /> : <Bot className="h-5 w-5 text-primary" />}
                        <div>
                          <span className="font-semibold text-sm">{type.label}</span>
                          <p className="text-xs text-muted-foreground mt-0.5">{type.description}</p>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Market Type Selection — prominent, full-width */}
              <div className="space-y-2">
                <Label>Market Type *</Label>
                <div className="grid grid-cols-2 gap-3">
                  {MARKET_TYPES.map((mt) => (
                    <button
                      key={mt.value}
                      onClick={() => {
                        if (botType === "ai_spot_swing" && mt.value !== "spot") return;
                        setMarketType(mt.value);
                        // Apply spot defaults when switching to spot
                        if (mt.value === "spot") {
                          setMaxLeverage(1);
                          setDefaultOrderType("limit");
                          setStopLossPct(SPOT_EXECUTION_DEFAULTS.stopLossPct);
                          setTakeProfitPct(SPOT_EXECUTION_DEFAULTS.takeProfitPct);
                          setTrailingStopEnabled(true);
                          setTrailingStopPct(SPOT_EXECUTION_DEFAULTS.trailingStopPct);
                          setMaxHoldTimeHours(SPOT_EXECUTION_DEFAULTS.maxHoldTimeHours);
                          setThrottleMode("conservative");
                          setMaxPositions(SPOT_RISK_DEFAULTS.maxPositions);
                          setMaxPositionsPerSymbol(SPOT_RISK_DEFAULTS.maxPositionsPerSymbol);
                          setEnabledSymbols(["BTCUSDT"]);
                        } else {
                          setEnabledSymbols(["BTC-USDT-SWAP"]);
                        }
                      }}
                      className={`rounded-xl border-2 p-4 text-left transition-all ${
                        marketType === mt.value
                          ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                          : botType === "ai_spot_swing" && mt.value !== "spot"
                          ? "border-border/50 opacity-50 cursor-not-allowed"
                          : "border-border hover:border-primary/50"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-2xl">{mt.icon}</span>
                        <div>
                          <span className="font-semibold text-sm">{mt.label}</span>
                          <p className="text-xs text-muted-foreground mt-0.5">{mt.description}</p>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
                {botType === "ai_spot_swing" && (
                  <p className="text-xs text-primary">AI spot/swing bots are locked to spot market structure and slower execution defaults.</p>
                )}
              </div>

              <div className="grid gap-6 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Bot Name *</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={marketType === "spot" ? "e.g., BTC Accumulator" : "e.g., Scalper Alpha"}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Allocator Role</Label>
                  <div className="grid grid-cols-3 gap-2">
                    {ALLOCATOR_ROLES.map((role) => (
                      <button
                        key={role.value}
                        onClick={() => setAllocatorRole(role.value)}
                        className={`rounded-lg border p-3 text-left transition-all ${
                          allocatorRole === role.value
                            ? "border-primary bg-primary/10"
                            : "border-border hover:border-primary/50"
                        }`}
                      >
                        <span className="font-medium text-sm">{role.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Strategy Template</Label>
                  <Select
                    value={templateId}
                    onChange={(e) => setTemplateId(e.target.value)}
                    options={[
                      { value: "", label: "No template (custom)" },
                      ...(templatesData?.templates || []).map((t) => ({
                        value: t.id,
                        label: t.name,
                      })),
                    ]}
                  />
                </div>

                <div className="space-y-2 md:col-span-2">
                  <Label>Description</Label>
                  <Textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Optional description of this bot's purpose"
                    rows={3}
                  />
                </div>
              </div>
            </div>
          )}

          {/* EXCHANGE STEP */}
          {step === "exchange" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold mb-1">Exchange Connection</h2>
                <p className="text-muted-foreground text-sm">Select credentials and trading environment</p>
              </div>

              {isLoadingExchangeAccounts ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : verifiedAccounts.length === 0 ? (
                <div className="text-center py-12">
                  <AlertCircle className="h-12 w-12 mx-auto text-amber-400 mb-4" />
                  <h3 className="font-medium mb-2">No Verified Exchange Accounts</h3>
                  <p className="text-sm text-muted-foreground mb-4">
                    Add exchange accounts in Settings → Exchange Accounts before creating a bot
                  </p>
                  <Button asChild variant="outline">
                    <Link to="/settings/exchange-accounts">Go to Exchange Accounts</Link>
                  </Button>
                </div>
              ) : (
                <>
                  <div className="space-y-3">
                    <Label>Select Exchange Account</Label>
                    <div className="grid gap-3 md:grid-cols-2">
                      {verifiedAccounts.map((account) => {
                        const hasBalance = account.available_balance !== undefined && account.available_balance !== null;
                        const balanceDisplay = hasBalance 
                          ? `$${Number(account.available_balance).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                          : 'Balance unknown';
                        
                        return (
                          <button
                            key={account.id}
                            onClick={() => {
                              setCredentialId(account.id);
                              // Don't auto-switch environment - user can choose any environment
                              // Demo credentials can be used with live mode for testing
                            }}
                            className={`rounded-xl border p-4 text-left transition-all ${
                              account.id === credentialId
                                ? "border-primary bg-primary/10 shadow-sm"
                                : "border-border hover:border-primary/50"
                            }`}
                          >
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <Server className="h-5 w-5 text-primary" />
                                <span className="font-semibold uppercase">{account.venue}</span>
                              </div>
                              <Badge variant="outline" className="text-[10px] capitalize">{account.environment}</Badge>
                            </div>
                            <p className="text-xs text-muted-foreground mb-2">{account.label}</p>
                            
                            <div className="rounded-lg bg-muted/50 p-2 mb-2">
                              <div className="flex items-center justify-between">
                                <span className="text-xs text-muted-foreground">Available</span>
                                <span className={`text-sm font-semibold ${hasBalance ? 'text-foreground' : 'text-muted-foreground'}`}>
                                  {balanceDisplay}
                                </span>
                              </div>
                            </div>
                            
                            <div className="flex items-center gap-1">
                              <Check className="h-3 w-3 text-green-400" />
                              <span className="text-xs text-green-400">Verified</span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <Label>Environment</Label>
                      {isEnvironmentLocked && (
                        <Badge variant="outline" className="text-xs gap-1">
                          <Lock className="h-3 w-3" />
                          Locked
                        </Badge>
                      )}
                    </div>
                    
                    {isEnvironmentLocked ? (
                      // Locked environment for existing bot configs
                      <div className="space-y-2">
                        <div className={`rounded-lg px-4 py-2.5 text-sm font-medium border ${
                          ENVIRONMENTS.find(e => e.value === environment)?.bgColor || 'bg-muted'
                        } ${ENVIRONMENTS.find(e => e.value === environment)?.color || ''} shadow-sm border-transparent`}>
                          {ENVIRONMENTS.find(e => e.value === environment)?.label || environment}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          Environment is locked after creation to prevent mixing live and paper trades on the same bot.
                        </p>
                      </div>
                    ) : (
                      // Editable environment for new bot configs
                      <>
                        <div className="flex gap-2">
                          {allowedEnvironments.map((env) => (
                            <button
                              key={env.value}
                              onClick={() => setEnvironment(env.value as BotEnvironment)}
                              className={`rounded-lg px-4 py-2.5 text-sm font-medium transition-all border ${
                                environment === env.value
                                  ? `${env.bgColor} ${env.color} shadow-sm border-transparent`
                                  : "text-foreground border-border hover:border-primary/50 bg-muted/50"
                              }`}
                            >
                              {env.label}
                            </button>
                          ))}
                        </div>
                        {selectedAccount?.is_demo && environment === 'live' && (
                          <p className="text-xs text-emerald-500 flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            Demo + Live: Real orders on demo exchange (no real funds at risk)
                          </p>
                        )}
                        {!selectedAccount?.is_demo && environment === 'live' && (
                          <p className="text-xs text-amber-500 flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            ⚠️ Mainnet + Live: Real orders with REAL FUNDS!
                          </p>
                        )}
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {/* CAPITAL STEP */}
          {step === "capital" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold mb-1">Capital & Risk</h2>
                <p className="text-muted-foreground text-sm">Configure trading capital and risk parameters</p>
              </div>

              {selectedAccount && (
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="rounded-lg bg-primary/20 p-2">
                        <Wallet className="h-5 w-5 text-primary" />
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground">
                          Exchange Balance (<span className="uppercase font-medium text-foreground">{selectedAccount.venue}</span>)
                        </p>
                        <p className="text-xl font-bold">
                          {selectedAccount.available_balance !== undefined
                            ? `$${Number(selectedAccount.available_balance).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                            : 'Balance unknown'}
                        </p>
                      </div>
                    </div>
                  </div>

                  {selectedAccount.available_balance !== undefined && (
                    <div className="rounded-lg bg-background/50 p-3 space-y-2">
                      {budgetInfo.allocatedToOthers > 0 && (
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground flex items-center gap-1">
                            <Bot className="h-3 w-3" />
                            Other bots ({budgetInfo.otherBotCount})
                          </span>
                          <span className="font-mono text-amber-400">
                            −${budgetInfo.allocatedToOthers.toLocaleString()}
                          </span>
                        </div>
                      )}
                      <Separator className="my-1" />
                      <div className="flex items-center justify-between text-sm font-medium">
                        <span className={budgetInfo.remainingAllocatable !== undefined && budgetInfo.remainingAllocatable <= 0 ? 'text-red-400' : 'text-green-400'}>
                          {editingBot ? 'Available for this bot' : 'Remaining for new bot'}
                        </span>
                        <span className={`font-mono ${budgetInfo.remainingAllocatable !== undefined && budgetInfo.remainingAllocatable <= 0 ? 'text-red-400' : 'text-green-400'}`}>
                          ${(budgetInfo.remainingAllocatable ?? 0).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="grid gap-6 lg:grid-cols-2">
                <div className="space-y-6">
                  <div className="space-y-2">
                    <Label>Trading Capital (USD) *</Label>
                    <Input
                      type="number"
                      min="10"
                      value={tradingCapital}
                      onChange={(e) => setTradingCapital(e.target.value ? Number(e.target.value) : "")}
                      placeholder={budgetInfo.remainingAllocatable !== undefined 
                        ? `Max: $${budgetInfo.remainingAllocatable.toLocaleString()}` : 'e.g., 1000'}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label>Position Size %</Label>
                    <Input
                      type="number"
                      min="0.1"
                      step="0.1"
                      value={positionSizePct}
                      onChange={(e) => setPositionSizePct(e.target.value ? Number(e.target.value) : "")}
                    />
                    <p className="text-xs text-muted-foreground">% of capital per trade</p>
                  </div>

                  {marketType !== "spot" && (
                  <div className="space-y-2">
                    <Label>Max Leverage</Label>
                    <Input
                      type="number"
                      min="1"
                      max={policyData?.policy?.max_leverage || 10}
                      step="1"
                      value={maxLeverage}
                      onChange={(e) => setMaxLeverage(e.target.value ? Number(e.target.value) : "")}
                    />
                    <p className="text-xs text-muted-foreground">
                      Policy max: {policyData?.policy?.max_leverage || 10}x
                    </p>
                  </div>
                  )}

                  <div className="space-y-2">
                    <Label>Notes</Label>
                    <Textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="Optional notes about this configuration"
                      rows={2}
                    />
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-muted/30 p-5">
                  <h3 className="font-medium mb-4 flex items-center gap-2">
                    <PieChart className="h-4 w-4 text-primary" />
                    Impact Preview
                  </h3>
                  <div className="space-y-4">
                    <div className="flex justify-between items-center py-2 border-b border-border/50">
                      <span className="text-sm text-muted-foreground">Max Notional Exposure</span>
                      <span className="font-mono font-semibold">{formatCurrency(previewMaxExposure)}</span>
                    </div>
                    <div className="flex justify-between items-center py-2 border-b border-border/50">
                      <span className="text-sm text-muted-foreground">Typical Trade Size</span>
                      <span className="font-mono font-semibold">{formatCurrency(previewTradeSize)}</span>
                    </div>
                    <div className="flex justify-between items-center py-2">
                      <span className="text-sm text-muted-foreground">Policy Compliance</span>
                      <div className="flex items-center gap-1">
                        <Check className="h-4 w-4 text-green-400" />
                        <span className="text-sm text-green-400">OK</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ADVANCED STEP */}
          {step === "advanced" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold mb-1">Advanced Settings</h2>
                <p className="text-muted-foreground text-sm">Configure risk limits and execution parameters</p>
              </div>

              <div className="rounded-xl border border-border p-5 space-y-4">
                <h3 className="font-semibold flex items-center gap-2">
                  <Shield className="h-4 w-4 text-primary" />
                  Risk Limits
                </h3>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label>Max Positions</Label>
                    <Input type="number" min="1" max="20" value={maxPositions} onChange={(e) => setMaxPositions(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Daily Loss (%)</Label>
                    <Input type="number" min="0.1" max="100" step="0.1" value={maxDailyLossPct} onChange={(e) => setMaxDailyLossPct(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Exposure (%)</Label>
                    <Input type="number" min="10" max="100" value={maxTotalExposurePct} onChange={(e) => setMaxTotalExposurePct(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Exposure/Symbol (%)</Label>
                    <Input type="number" min="1" max="100" step="0.1" value={maxExposurePerSymbolPct} onChange={(e) => setMaxExposurePerSymbolPct(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Min Position (USD)</Label>
                    <Input type="number" min="0" step="1" value={minPositionSizeUsd} onChange={(e) => setMinPositionSizeUsd(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Position (USD)</Label>
                    <Input type="number" min="0" step="1" value={maxPositionSizeUsd} onChange={(e) => setMaxPositionSizeUsd(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Leverage Mode</Label>
                    <Select
                      value={leverageMode}
                      onChange={(e) => setLeverageMode(e.target.value as "isolated" | "cross")}
                      options={[
                        { value: "isolated", label: "Isolated" },
                        { value: "cross", label: "Cross" },
                      ]}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Positions/Symbol</Label>
                    <Input type="number" min="1" max="10" value={maxPositionsPerSymbol} onChange={(e) => setMaxPositionsPerSymbol(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Loss/Symbol (%)</Label>
                    <Input type="number" min="0.1" max="50" step="0.1" value={maxDailyLossPerSymbolPct} onChange={(e) => setMaxDailyLossPerSymbolPct(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Positions/Strategy</Label>
                    <Input type="number" min="0" max="20" value={maxPositionsPerStrategy} onChange={(e) => setMaxPositionsPerStrategy(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Drawdown (%)</Label>
                    <Input type="number" min="0" max="100" step="0.1" value={maxDrawdownPct} onChange={(e) => setMaxDrawdownPct(Number(e.target.value))} />
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-border p-5 space-y-4">
                <h3 className="font-semibold flex items-center gap-2">
                  <Zap className="h-4 w-4 text-primary" />
                  Execution Settings
                </h3>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label>Order Type</Label>
                    <Select
                      value={defaultOrderType}
                      onChange={(e) => setDefaultOrderType(e.target.value as "market" | "limit")}
                      options={[
                        { value: "market", label: "Market" },
                        { value: "limit", label: "Limit" },
                      ]}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Stop Loss (%)</Label>
                    <Input type="number" min="0.1" max="50" step="0.1" value={stopLossPct} onChange={(e) => setStopLossPct(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Take Profit (%)</Label>
                    <Input type="number" min="0.1" max="100" step="0.1" value={takeProfitPct} onChange={(e) => setTakeProfitPct(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Hold (hours)</Label>
                    <Input type="number" min="0.1" max="168" step="0.1" value={maxHoldTimeHours} onChange={(e) => setMaxHoldTimeHours(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Trade Interval (sec)</Label>
                    <Input type="number" min="0" max="60" value={minTradeIntervalSec} onChange={(e) => setMinTradeIntervalSec(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Exec Timeout (sec)</Label>
                    <Input type="number" min="1" max="60" value={executionTimeoutSec} onChange={(e) => setExecutionTimeoutSec(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Intent Max Age (sec)</Label>
                    <Input type="number" min="0" max="3600" value={orderIntentMaxAgeSec} onChange={(e) => setOrderIntentMaxAgeSec(Number(e.target.value))} />
                  </div>
                </div>

                <Separator />

                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <Label>Trailing Stop</Label>
                      <p className="text-xs text-muted-foreground">Follow price for better exits</p>
                    </div>
                    <Switch checked={trailingStopEnabled} onCheckedChange={setTrailingStopEnabled} />
                  </div>
                  {trailingStopEnabled && (
                    <div className="pl-4 border-l-2 border-primary/30 space-y-2">
                      <Label>Trailing Distance (%)</Label>
                      <Input type="number" min="0.1" max="20" step="0.1" value={trailingStopPct} onChange={(e) => setTrailingStopPct(Number(e.target.value))} className="max-w-32" />
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <div>
                      <Label>Volatility Filter</Label>
                      <p className="text-xs text-muted-foreground">Pause during high volatility</p>
                    </div>
                    <Switch checked={enableVolatilityFilter} onCheckedChange={setEnableVolatilityFilter} />
                  </div>
                </div>

                <Separator />

                <div className="space-y-3">
                  <div>
                    <Label>Throttle Mode</Label>
                    <p className="text-xs text-muted-foreground mb-2">Controls trading frequency and cooldown behavior</p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {THROTTLE_MODES.map((mode) => (
                      <button
                        key={mode.value}
                        type="button"
                        onClick={() => setThrottleMode(mode.value)}
                        className={`flex items-center gap-3 p-3 rounded-lg border transition-colors text-left ${
                          throttleMode === mode.value
                            ? "border-primary bg-primary/10"
                            : "border-border hover:border-primary/50"
                        }`}
                      >
                        <span className="text-xl">{mode.icon}</span>
                        <div className="flex-1">
                          <div className="font-medium text-sm">{mode.label}</div>
                          <div className="text-xs text-muted-foreground">{mode.description}</div>
                        </div>
                        {throttleMode === mode.value && (
                          <div className="w-2 h-2 rounded-full bg-primary" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {botType === "ai_spot_swing" && (
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-5 space-y-4">
                  <h3 className="font-semibold flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-primary" />
                    AI Spot / Swing Settings
                  </h3>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Confidence Floor</Label>
                      <Input
                        type="number"
                        min="0.5"
                        max="0.99"
                        step="0.01"
                        value={aiConfidenceFloor}
                        onChange={(e) => setAiConfidenceFloor(Number(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Default Mode</Label>
                      <div className="rounded-lg border border-border bg-background px-3 py-2 text-sm">
                        {aiShadowMode ? "Shadow only" : "Live routed"}
                      </div>
                      <p className="text-xs text-muted-foreground">New AI bots default to shadow mode for safe rollout.</p>
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-3">
                      <div>
                        <Label>Require sentiment/context</Label>
                        <p className="text-xs text-muted-foreground">Abstain when enriched context is missing or stale</p>
                      </div>
                      <Switch checked={aiSentimentRequired} onCheckedChange={setAiSentimentRequired} />
                    </div>
                    <div className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-3">
                      <div>
                        <Label>Require baseline alignment</Label>
                        <p className="text-xs text-muted-foreground">Only promote AI ideas when baseline direction agrees</p>
                      </div>
                      <Switch checked={aiRequireBaselineAlignment} onCheckedChange={setAiRequireBaselineAlignment} />
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <Label>Allowed Sessions</Label>
                      <p className="text-xs text-muted-foreground mb-2">Select when the AI profile may participate.</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {["asia", "london", "ny"].map((session) => {
                        const active = aiSessions.includes(session);
                        return (
                          <button
                            key={session}
                            type="button"
                            onClick={() =>
                              setAiSessions((current) =>
                                active ? current.filter((item) => item !== session) : [...current, session]
                              )
                            }
                            className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
                              active ? "border-primary bg-primary/10 text-primary" : "border-border hover:border-primary/50"
                            }`}
                          >
                            {session.toUpperCase()}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* SYMBOLS STEP */}
          {step === "symbols" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold mb-1">Trading Symbols</h2>
                <p className="text-muted-foreground text-sm">Select symbols to trade</p>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                {getSymbolsForMarketType(marketType).map((opt) => {
                  const checked = enabledSymbols.includes(opt.id);
                  return (
                    <div
                      key={opt.id}
                      className={`rounded-xl border p-4 transition-all cursor-pointer ${
                        checked ? "border-primary bg-primary/10" : "border-border hover:border-primary/50"
                      }`}
                      onClick={() => {
                        setEnabledSymbols(prev =>
                          checked ? prev.filter(s => s !== opt.id) : [...prev, opt.id]
                        );
                      }}
                    >
                      <div className="flex items-center gap-3">
                        <Checkbox checked={checked} onChange={() => {}} />
                        <div>
                          <span className="font-semibold">{opt.label}</span>
                          <p className="text-xs text-muted-foreground">{opt.hint}</p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {enabledSymbols.length > 0 && (
                <div className="rounded-xl border border-border bg-muted/30 p-5">
                  <h3 className="font-medium mb-4">Per-Symbol Overrides (Optional)</h3>
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {enabledSymbols.map((sym) => (
                      <div key={sym} className="rounded-lg border border-border bg-background p-4">
                        <div className="font-medium mb-3">{sym.replace("-USDT-SWAP", "")}</div>
                        <div className="space-y-3">
                          <div className="space-y-1">
                            <Label className="text-xs">Min Notional (USD)</Label>
                            <Input
                              type="number"
                              min="0"
                              placeholder="Default"
                              value={symbolOverrides[sym]?.minNotionalUsd ?? ""}
                              onChange={(e) =>
                                setSymbolOverrides(prev => ({
                                  ...prev,
                                  [sym]: { ...prev[sym], minNotionalUsd: e.target.value ? Number(e.target.value) : undefined },
                                }))
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">Max Leverage</Label>
                            <Input
                              type="number"
                              min="1"
                              placeholder="Default"
                              value={symbolOverrides[sym]?.maxLeverage ?? ""}
                              onChange={(e) =>
                                setSymbolOverrides(prev => ({
                                  ...prev,
                                  [sym]: { ...prev[sym], maxLeverage: e.target.value ? Number(e.target.value) : undefined },
                                }))
                              }
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* REVIEW STEP */}
          {step === "review" && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold mb-1">Review & Activate</h2>
                <p className="text-muted-foreground text-sm">Review your configuration before creating</p>
              </div>

              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Card className="border-border/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <Bot className="h-4 w-4 text-muted-foreground" />
                      Bot Identity
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Name</span>
                      <span className="font-medium">{name}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Role</span>
                      <Badge className={getRoleBadge(allocatorRole)}>{allocatorRole}</Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Type</span>
                      <Badge variant="outline">{botType === "ai_spot_swing" ? "AI Spot / Swing" : "Standard"}</Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Market</span>
                      <Badge className={getMarketTypeBadge(marketType)}>{getMarketTypeLabel(marketType)}</Badge>
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <Server className="h-4 w-4 text-muted-foreground" />
                      Exchange
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Exchange</span>
                      <span className="uppercase">{selectedAccount?.venue}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Environment</span>
                      <Badge className={getEnvironmentBadge(environment)}>{environment}</Badge>
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <DollarSign className="h-4 w-4 text-muted-foreground" />
                      Capital
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Capital</span>
                      <span className="font-mono">{formatCurrency(typeof tradingCapital === "number" ? tradingCapital : 0)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Position Size</span>
                      <span className="font-mono">{positionSizePct}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Max Leverage</span>
                      <span className="font-mono">{maxLeverage}x</span>
                    </div>
                  </CardContent>
                </Card>

                <Card className="border-border/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <Layers className="h-4 w-4 text-muted-foreground" />
                      Symbols
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {enabledSymbols.map(sym => (
                        <Badge key={sym} variant="outline" className="font-mono">
                          {sym.replace("-USDT-SWAP", "")}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>

                {botType === "ai_spot_swing" && (
                  <Card className="border-border/50">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-muted-foreground" />
                        AI Settings
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Provider</span>
                        <span className="font-mono">DeepSeek</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Mode</span>
                        <Badge variant="outline">{aiShadowMode ? "Shadow" : "Live"}</Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Confidence</span>
                        <span className="font-mono">{aiConfidenceFloor.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Sessions</span>
                        <span className="font-mono">{aiSessions.map((s) => s.toUpperCase()).join(", ")}</span>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>

              <div className="flex items-center gap-3 p-4 rounded-lg bg-muted/30 border border-border">
                <Switch checked={activate} onChange={(e) => setActivate(e.target.checked)} />
                <div>
                  <span className="font-medium">Activate after creation</span>
                  <p className="text-xs text-muted-foreground">
                    {botType === "ai_spot_swing"
                      ? "Create the runtime config immediately. AI routing still defaults to shadow mode."
                      : "Start trading immediately after bot is created"}
                  </p>
                </div>
              </div>
            </div>
          )}
        </CardContent>

        {/* Footer */}
        <Separator className="bg-border/50" />
        <div className="flex items-center justify-between p-4">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <div className="flex gap-2">
            {canGoBack && (
              <Button variant="outline" onClick={prevStep}>
                Back
              </Button>
            )}
            {isLastStep ? (
              <Button onClick={handleSubmit} disabled={isPending}>
                {isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                {editingBot ? "Update Bot" : "Create & Activate"}
              </Button>
            ) : (
              <Button onClick={nextStep}>
                Next
                <ArrowRight className="h-4 w-4 ml-2" />
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

export default BotBuilder;
