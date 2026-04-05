/**
 * Bot Edit Sheet Component
 * Tabbed editor for existing bot configurations
 */

import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Bot,
  Server,
  DollarSign,
  Shield,
  Zap,
  CircleDot,
  Loader2,
  History,
  Layers,
  ExternalLink,
  AlertCircle,
} from "lucide-react";
import { cn } from "../../lib/utils";

import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "../../components/ui/sheet";

import {
  useStrategyTemplates,
  useUpdateBotInstance,
  useUpdateBotExchangeConfig,
  useRollbackBotExchangeConfig,
  useUserProfiles,
} from "../../lib/api/hooks";
import { useExchangeAccounts } from "../../lib/api/exchange-accounts-hooks";

import { IdentityForm } from "./forms/IdentityForm";
import { ExchangeForm } from "./forms/ExchangeForm";
import { CapitalForm } from "./forms/CapitalForm";
import { RiskForm } from "./forms/RiskForm";
import { ExecutionForm } from "./forms/ExecutionForm";
import { SymbolsForm } from "./forms/SymbolsForm";
import { VersionHistory } from "./VersionHistory";

import {
  initializeFormFromBot,
  DEFAULT_RISK_STATE,
  DEFAULT_EXECUTION_STATE,
} from "./types";
import type {
  BotInstance,
  BotExchangeConfig,
  BotEnvironment,
  ExchangeAccountOption,
  RiskFormState,
  ExecutionFormState,
  TradingMode,
} from "./types";
import type { AllocatorRole } from "../../lib/api/types";
import { useConfigValidation } from "../../lib/api/config-validation-hooks";
import { ConfigValidationBanner, ValidationIndicator } from "./ConfigValidationBanner";
import type { BotConfigForValidation } from "../../lib/api/config-validation";

interface BotEditSheetProps {
  bot: BotInstance | null;
  onClose: () => void;
}

// Active Profiles View Component (Chessboard System)
// Shows which profiles are active for the bot's environment
// The Profile Router dynamically selects from these based on market conditions
function ActiveProfilesView({ environment }: { environment: string }) {
  const { data: profilesData, isLoading } = useUserProfiles({ environment });
  
  const profiles = profilesData?.profiles || [];
  const activeProfiles = profiles.filter((p: any) => p.is_active);
  const inactiveProfiles = profiles.filter((p: any) => !p.is_active);

  const envLabel = environment === 'dev' ? 'Development' : environment === 'paper' ? 'Paper Trading' : 'Live Trading';
  const envColor = environment === 'dev' ? 'blue' : environment === 'paper' ? 'amber' : 'emerald';

  return (
    <div className="space-y-6">
      {/* Explanation Banner */}
      <div className={cn(
        "p-4 rounded-lg border",
        `bg-${envColor}-500/10 border-${envColor}-500/30`
      )}>
        <div className="flex items-start gap-3">
          <Layers className={`h-5 w-5 text-${envColor}-400 flex-shrink-0 mt-0.5`} />
          <div>
            <h3 className={`font-medium text-${envColor}-400`}>Chessboard Profile System</h3>
            <p className="text-sm text-muted-foreground mt-1">
              The bot's <strong>Profile Router</strong> automatically selects the best profile from your 
              active profiles based on current market conditions (trend, volatility, session, etc.).
            </p>
            <p className="text-xs text-muted-foreground mt-2">
              Activate multiple profiles below — the router will dynamically pick the optimal one for each trade.
            </p>
          </div>
        </div>
      </div>

      {/* Active Profiles */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
            Active Profiles ({activeProfiles.length})
          </h3>
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.open('/dashboard/profiles', '_blank')}
          >
            <ExternalLink className="h-3 w-3 mr-1" />
            Manage Profiles
          </Button>
        </div>
        
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : activeProfiles.length === 0 ? (
          <div className="p-4 rounded-lg border border-dashed border-amber-500/30 bg-amber-500/5 text-center">
            <AlertCircle className="h-6 w-6 mx-auto mb-2 text-amber-500" />
            <p className="text-sm text-amber-500 font-medium">No active profiles for {envLabel}</p>
            <p className="text-xs text-muted-foreground mt-1">
              Activate profiles in the Profiles page to enable trading
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => window.open('/dashboard/profiles', '_blank')}
            >
              Go to Profiles
            </Button>
          </div>
        ) : (
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {activeProfiles.map((profile: any) => (
              <div
                key={profile.id}
                className="p-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{profile.name}</span>
                      <Badge className="text-[10px] bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                        Active
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-muted-foreground">
                        v{profile.version} • {profile.strategy_composition?.length || 0} strategies
                      </span>
                    </div>
                    {profile.conditions && (
                      <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                        {profile.conditions.required_trend && profile.conditions.required_trend !== 'any' && (
                          <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                            {profile.conditions.required_trend}
                          </Badge>
                        )}
                        {profile.conditions.required_volatility && profile.conditions.required_volatility !== 'any' && (
                          <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                            {profile.conditions.required_volatility} vol
                          </Badge>
                        )}
                        {profile.conditions.required_session && profile.conditions.required_session !== 'any' && (
                          <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                            {profile.conditions.required_session}
                          </Badge>
                        )}
                      </div>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => window.open(`/dashboard/profile-editor?id=${profile.id}`, "_blank")}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Inactive Profiles (collapsed) */}
      {inactiveProfiles.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-gray-500"></span>
            Inactive Profiles ({inactiveProfiles.length})
          </h3>
          <div className="space-y-2 max-h-[150px] overflow-y-auto">
            {inactiveProfiles.map((profile: any) => (
              <div
                key={profile.id}
                className="p-3 rounded-lg border border-border bg-muted/30"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-muted-foreground">{profile.name}</span>
                    <div className="text-xs text-muted-foreground/70 mt-0.5">
                      v{profile.version} • {profile.strategy_composition?.length || 0} strategies
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => window.open(`/dashboard/profile-editor?id=${profile.id}`, "_blank")}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

type TabId = "identity" | "exchange" | "capital" | "risk" | "execution" | "symbols" | "profile" | "history";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "identity", label: "Identity", icon: <Bot className="h-4 w-4" /> },
  { id: "exchange", label: "Exchange", icon: <Server className="h-4 w-4" /> },
  { id: "capital", label: "Capital", icon: <DollarSign className="h-4 w-4" /> },
  { id: "risk", label: "Risk", icon: <Shield className="h-4 w-4" /> },
  { id: "execution", label: "Execution", icon: <Zap className="h-4 w-4" /> },
  { id: "symbols", label: "Symbols", icon: <CircleDot className="h-4 w-4" /> },
  { id: "profile", label: "Profile", icon: <Layers className="h-4 w-4" /> },
  { id: "history", label: "History", icon: <History className="h-4 w-4" /> },
];

export function BotEditSheet({ bot, onClose }: BotEditSheetProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>("identity");

  // Get the first exchange config (primary config)
  const primaryConfig = bot?.exchangeConfigs?.[0];

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [allocatorRole, setAllocatorRole] = useState("core");
  const [templateId, setTemplateId] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [environment, setEnvironment] = useState<BotEnvironment>("paper");
  const [tradingMode, setTradingMode] = useState<TradingMode>("paper"); // Bot-level trading mode
  const [tradingCapital, setTradingCapital] = useState<number | "">(1000);
  const [enabledSymbols, setEnabledSymbols] = useState<string[]>(["BTC-USDT-SWAP"]);
  const [risk, setRisk] = useState<RiskFormState>(DEFAULT_RISK_STATE);
  const [execution, setExecution] = useState<ExecutionFormState>(DEFAULT_EXECUTION_STATE);
  const [notes, setNotes] = useState("");

  // Hooks
  const { data: templatesData, isLoading: isLoadingTemplates } = useStrategyTemplates();
  const { data: exchangeAccountsData } = useExchangeAccounts();
  const updateBotMutation = useUpdateBotInstance();
  const updateConfigMutation = useUpdateBotExchangeConfig();
  const rollbackMutation = useRollbackBotExchangeConfig();

  const exchangeAccounts = (exchangeAccountsData || []) as ExchangeAccountOption[];
  const verifiedAccounts = exchangeAccounts.filter((a) => a.status === "verified");
  const selectedAccount = verifiedAccounts.find((a) => a.id === credentialId);
  const currentEnvironment = (primaryConfig?.environment as BotEnvironment) || environment;

  // Initialize form from bot data
  useEffect(() => {
    if (bot) {
      const formData = initializeFormFromBot(bot, primaryConfig);
      setName(formData.name || "");
      setDescription(formData.description || "");
      setAllocatorRole(formData.allocatorRole || "core");
      setTemplateId(formData.templateId || "");
      setCredentialId(formData.credentialId || "");
      setEnvironment(formData.environment || "paper");
      setTradingMode(formData.tradingMode || "paper"); // Bot-level trading mode
      setTradingCapital(formData.tradingCapital ?? 1000);
      setEnabledSymbols(formData.enabledSymbols || ["BTC-USDT-SWAP"]);
      setRisk(formData.risk || DEFAULT_RISK_STATE);
      setExecution(formData.execution || DEFAULT_EXECUTION_STATE);
    }
  }, [bot, primaryConfig]);

  const handleSave = async () => {
    if (!bot) return;

    try {
      // Update bot instance (identity + default configs + trading mode)
      await updateBotMutation.mutateAsync({
        botId: bot.id,
        data: {
          name,
          description,
          allocator_role: allocatorRole as AllocatorRole,
          strategy_template_id: templateId || undefined,
          default_risk_config: risk as any,
          default_execution_config: execution as any,
        } as any,
      });

      // Update primary config if exists
      if (primaryConfig) {
        await updateConfigMutation.mutateAsync({
          botId: bot.id,
          configId: primaryConfig.id,
          data: {
            environment: currentEnvironment,
            trading_capital_usd: typeof tradingCapital === "number" ? tradingCapital : undefined,
            enabled_symbols: enabledSymbols,
            risk_config: risk,
            execution_config: execution,
          },
        });
      }

      toast.success("Bot updated successfully");
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      onClose();
    } catch (error: any) {
      toast.error(error?.message || "Failed to update bot");
    }
  };

  const isPending = updateBotMutation.isPending || updateConfigMutation.isPending;

  // Build config object for validation
  const configForValidation: BotConfigForValidation = {
    tradingMode,
    environment: currentEnvironment,
    venue: selectedAccount?.venue || 'binance',
    isDemo: selectedAccount?.is_demo || false,
    tradingCapitalUsd: tradingCapital,
    enabledSymbols,
    riskConfig: {
      maxPositions: risk.maxPositions,
      positionSizePct: risk.positionSizePct,
      minPositionSizeUsd: risk.minPositionSizeUsd,
      maxPositionSizeUsd: risk.maxPositionSizeUsd,
      maxPositionsPerStrategy: risk.maxPositionsPerStrategy,
      maxDailyLossPct: risk.maxDailyLossPct,
      maxTotalExposurePct: risk.maxTotalExposurePct,
      maxExposurePerSymbolPct: risk.maxExposurePerSymbolPct || risk.positionSizePct,
      maxLeverage: risk.maxLeverage,
      leverageMode: risk.leverageMode,
      maxPositionsPerSymbol: risk.maxPositionsPerSymbol,
      maxDailyLossPerSymbolPct: risk.maxDailyLossPerSymbolPct,
      maxDrawdownPct: risk.maxDrawdownPct,
    },
    executionConfig: {
      stopLossPct: execution.stopLossPct,
      takeProfitPct: execution.takeProfitPct,
      trailingStopEnabled: execution.trailingStopEnabled,
      trailingStopPct: execution.trailingStopPct,
      maxHoldTimeHours: execution.maxHoldTimeHours,
      defaultOrderType: execution.defaultOrderType,
      minTradeIntervalSec: execution.minTradeIntervalSec,
      executionTimeoutSec: execution.executionTimeoutSec,
      enableVolatilityFilter: execution.enableVolatilityFilter,
      throttleMode: execution.throttleMode,
      orderIntentMaxAgeSec: execution.orderIntentMaxAgeSec,
    },
  };

  // Real-time validation
  const validation = useConfigValidation(configForValidation);
  const hasValidationErrors = validation.errors.length > 0;

  if (!bot) return null;

  return (
    <Sheet open={!!bot} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-4xl flex flex-col h-full overflow-hidden">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" />
            Edit Bot Configuration
          </SheetTitle>
          <SheetDescription className="flex items-center gap-2">
            <span className="font-semibold text-foreground">{bot.name}</span>
            <Badge variant="outline" className="text-xs">
              {bot.allocator_role}
            </Badge>
            {primaryConfig && (
              <Badge variant="outline" className="text-xs capitalize">
                {primaryConfig.environment}
              </Badge>
            )}
            {primaryConfig?.config_version && (
              <Badge variant="outline" className="text-xs font-mono">
                v{primaryConfig.config_version}
              </Badge>
            )}
          </SheetDescription>
        </SheetHeader>

        {/* Tab Navigation */}
        <div className="mt-6 border-b border-border">
          <div className="flex gap-0.5 overflow-x-auto pb-px -mb-px">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap rounded-t-lg",
                  activeTab === tab.id
                    ? "border-primary text-primary bg-primary/5"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50"
                )}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Content */}
        <div className={cn(
          "mt-6 flex-1 min-h-0",
          activeTab === "history" ? "flex flex-col" : "overflow-y-auto space-y-6"
        )}>
          {activeTab === "identity" && (
            <IdentityForm
              name={name}
              setName={setName}
              description={description}
              setDescription={setDescription}
              allocatorRole={allocatorRole}
              setAllocatorRole={setAllocatorRole}
              tradingMode={tradingMode}
              setTradingMode={setTradingMode}
              templateId={templateId}
              setTemplateId={setTemplateId}
              templates={templatesData?.templates}
              isLoadingTemplates={isLoadingTemplates}
              notes={notes}
              setNotes={setNotes}
            />
          )}

          {activeTab === "exchange" && (
            <ExchangeForm
              credentialId={credentialId}
              setCredentialId={setCredentialId}
              environment={currentEnvironment}
              setEnvironment={setEnvironment}
              verifiedAccounts={verifiedAccounts}
              isEditing={!!primaryConfig}
            />
          )}

          {activeTab === "capital" && (
            <CapitalForm
              tradingCapital={tradingCapital}
              setTradingCapital={setTradingCapital}
              risk={risk}
              setRisk={setRisk}
              selectedAccount={selectedAccount}
              isEditing={true}
            />
          )}

          {activeTab === "risk" && <RiskForm risk={risk} setRisk={setRisk} />}

          {activeTab === "execution" && (
            <ExecutionForm execution={execution} setExecution={setExecution} />
          )}

          {activeTab === "symbols" && (
            <SymbolsForm
              enabledSymbols={enabledSymbols}
              setEnabledSymbols={setEnabledSymbols}
            />
          )}

          {activeTab === "profile" && (
            <ActiveProfilesView
              environment={currentEnvironment}
            />
          )}

          {activeTab === "history" && primaryConfig && (
            <VersionHistory
              configId={primaryConfig.id}
              botId={bot.id}
              currentVersion={primaryConfig.config_version}
              onRollback={async (version) => {
                try {
                  await rollbackMutation.mutateAsync({
                    botId: bot.id,
                    configId: primaryConfig.id,
                    targetVersion: version.version_number,
                  });
                  toast.success(`Rolled back to v${version.version_number}`);
                  queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
                } catch (error: any) {
                  toast.error(error?.message || `Failed to rollback to v${version.version_number}`);
                }
              }}
            />
          )}

          {activeTab === "history" && !primaryConfig && (
            <div className="text-center py-8 text-muted-foreground">
              <History className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No exchange configuration found</p>
              <p className="text-xs mt-1">Configure an exchange to track version history</p>
            </div>
          )}
        </div>

        {/* Validation Banner */}
        {(validation.errors.length > 0 || validation.warnings.length > 0) && (
          <div className="mt-4 flex-shrink-0">
            <ConfigValidationBanner
              validation={validation}
              collapsible={true}
              defaultExpanded={validation.errors.length > 0}
            />
          </div>
        )}

        {/* Footer Actions */}
        <div className="mt-4 flex items-center gap-3 justify-between border-t pt-4 flex-shrink-0">
          <div className="flex items-center gap-2">
            <ValidationIndicator validation={validation} />
          </div>
          <div className="flex gap-3">
            <Button variant="outline" onClick={onClose} disabled={isPending}>
              Cancel
            </Button>
            <Button 
              onClick={handleSave} 
              disabled={isPending || !name.trim() || hasValidationErrors}
              variant="default"
              className={hasValidationErrors ? "bg-red-600 hover:bg-red-700 border-red-600" : ""}
            >
              {isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {hasValidationErrors ? "Fix Errors to Save" : "Save Changes"}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
