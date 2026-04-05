/**
 * Fleet Dashboard Component
 * 
 * Overview and management of all trading bots:
 * - KPI tiles for quick status overview
 * - Filterable/searchable bot table
 * - Quick actions (activate, deactivate, clone, delete)
 * - Bot detail drawer for quick inspection
 */

import { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { cn } from "../../lib/utils";
import {
  Plus,
  Loader2,
  Bot,
  Filter,
  RefreshCw,
  Search,
  MoreVertical,
  Play,
  Pause,
  Copy,
  Download,
  AlertTriangle,
  DollarSign,
  Activity,
  Layers,
  Eye,
  Edit,
  Trash2,
  Power,
  CircleDot,
  BarChart3,
  FileText,
} from "lucide-react";

import { Card, CardContent } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { Checkbox } from "../../components/ui/checkbox";
import { Tooltip, TooltipContent, TooltipTrigger } from "../../components/ui/tooltip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../../components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../components/ui/dropdown-menu";

import {
  useBotInstances,
  useActivateBotExchangeConfig,
  useDeactivateBotExchangeConfig,
  useDeleteBotInstance,
  useActiveConfig,
  useTenantRiskPolicy,
} from "../../lib/api/hooks";
import type { BotEnvironment, BotInstance, BotExchangeConfig, BotConfigState } from "../../lib/api/types";

import BotLogsPanel from "./BotLogsPanel";
import {
  ENVIRONMENTS,
  STATUS_FILTERS,
  getEnvironmentBadge,
  getCombinedTradingModeLabel,
  getCombinedTradingModeBadgeClass,
  getRoleBadge,
  getMarketTypeBadge,
  getMarketTypeLabel,
  formatCurrency,
  getStateBadge,
} from "./types";
import { usePreflightCheck } from "../../lib/api/config-validation-hooks";
import type { ValidationIssue, PreflightResult } from "../../lib/api/config-validation";

// ═══════════════════════════════════════════════════════════════
// LOCAL HELPERS
// ═══════════════════════════════════════════════════════════════

function getStateColor(state: BotConfigState) {
  switch (state) {
    case "running": return { text: "text-green-400", bg: "bg-green-500/20", border: "border-green-500/30" };
    case "paused": return { text: "text-amber-400", bg: "bg-amber-500/20", border: "border-amber-500/30" };
    case "ready": return { text: "text-blue-400", bg: "bg-blue-500/20", border: "border-blue-500/30" };
    case "blocked": return { text: "text-red-400", bg: "bg-red-600/20", border: "border-red-600/50" };
    case "error": return { text: "text-red-400", bg: "bg-red-500/20", border: "border-red-500/30" };
    case "created": return { text: "text-slate-400", bg: "bg-slate-500/20", border: "border-slate-500/30" };
    default: return { text: "text-slate-400", bg: "bg-slate-500/20", border: "border-slate-500/30" };
  }
}

// ═══════════════════════════════════════════════════════════════
// FLEET DASHBOARD
// ═══════════════════════════════════════════════════════════════

export interface FleetDashboardProps {
  onCreateBot: () => void;
  onEditBot: (bot: BotInstance) => void;
  onCloneBot: (bot: BotInstance) => void;
}

export function FleetDashboard({ onCreateBot, onEditBot, onCloneBot }: FleetDashboardProps) {
  const queryClient = useQueryClient();
  const [envFilter, setEnvFilter] = useState<BotEnvironment | "all">("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedConfigs, setSelectedConfigs] = useState<string[]>([]);
  const [drawerConfig, setDrawerConfig] = useState<{ bot: BotInstance; config: BotExchangeConfig } | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    type: "pause" | "deactivate" | "delete";
    config?: BotExchangeConfig;
    bot?: BotInstance;
  } | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  
  // Validation error modal state
  const [validationModal, setValidationModal] = useState<{
    open: boolean;
    bot?: BotInstance;
    config?: BotExchangeConfig;
    result?: PreflightResult;
  }>({ open: false });
  
  const preflightMutation = usePreflightCheck();

  const { data: botsData, isLoading } = useBotInstances();
  const { data: activeData } = useActiveConfig();
  const { data: policyData } = useTenantRiskPolicy();
  const activateMutation = useActivateBotExchangeConfig();
  const deactivateMutation = useDeactivateBotExchangeConfig();
  const deleteBotMutation = useDeleteBotInstance();

  // Flatten bots into configs for the fleet view
  const fleetItems = useMemo(() => {
    if (!botsData?.bots) return [];
    const items: { bot: BotInstance; config: BotExchangeConfig }[] = [];
    
    botsData.bots.forEach((bot) => {
      const configs = (bot.exchangeConfigs && bot.exchangeConfigs.length > 0)
        ? bot.exchangeConfigs
        : [{
            id: `placeholder-${bot.id}`,
            bot_instance_id: bot.id,
            exchange: bot["exchange"] || "n/a",
            exchange_account_id: bot["exchange_account_id"] || null,
            environment: "unconfigured",
            state: "unconfigured",
            enabled_symbols: [],
            trading_capital_usd: 0,
            risk_config: bot.default_risk_config || {},
            execution_config: bot.default_execution_config || {},
            is_active: bot.is_active,
          } as unknown as BotExchangeConfig];

      configs.forEach((config) => {
        // Apply filters
        if (envFilter !== "all" && config.environment !== envFilter) return;
        if (statusFilter !== "all" && config.state !== statusFilter) return;
        if (searchQuery) {
          const query = searchQuery.toLowerCase();
          const matchesBot = bot.name.toLowerCase().includes(query);
          const matchesSymbol = (config.enabled_symbols || []).some(s => s.toLowerCase().includes(query));
          const matchesExchange = config.exchange?.toLowerCase().includes(query);
          if (!matchesBot && !matchesSymbol && !matchesExchange) return;
        }
        items.push({ bot, config });
      });
    });
    
    return items;
  }, [botsData, envFilter, statusFilter, searchQuery]);

  // Calculate KPIs
  const kpis = useMemo(() => {
    const configs = fleetItems.map(i => i.config);
    return {
      running: configs.filter(c => c.state === "running").length,
      blocked: configs.filter(c => c.state === "blocked").length,
      errors: configs.filter(c => c.state === "error").length,
      totalCapital: configs.reduce((sum, c) => sum + (c.trading_capital_usd || 0), 0),
      liveCapital: configs.filter(c => c.environment === "live").reduce((sum, c) => sum + (c.trading_capital_usd || 0), 0),
      paperCapital: configs.filter(c => c.environment === "paper").reduce((sum, c) => sum + (c.trading_capital_usd || 0), 0),
      totalTrades: configs.reduce((sum, c) => sum + (c.trades_count || 0), 0),
    };
  }, [fleetItems]);

  const handleActivate = async (bot: BotInstance, config: BotExchangeConfig) => {
    try {
      // Run preflight check first
      const preflightResult = await preflightMutation.mutateAsync(bot.id);
      
      if (!preflightResult.canStart) {
        // Show validation error modal
        setValidationModal({
          open: true,
          bot,
          config,
          result: preflightResult,
        });
        return;
      }
      
      // Preflight passed, activate
      await activateMutation.mutateAsync({ botId: bot.id, configId: config.id });
      toast.success(`${bot.name} activated`);
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
    } catch (error: any) {
      // Check if this is a validation error from the backend
      if (error.message?.includes("validation") || error.message?.includes("Configuration")) {
        setValidationModal({
          open: true,
          bot,
          config,
          result: {
            canStart: false,
            reason: error.message,
            errors: [{
              id: "activation_error",
              severity: "error",
              field: null,
              message: error.message,
            }],
            warnings: [],
            info: [],
            summary: error.message,
          },
        });
      } else {
        toast.error(error.message || "Failed to activate");
      }
    }
  };

  const handleDeactivate = async (bot: BotInstance, config: BotExchangeConfig) => {
    try {
      await deactivateMutation.mutateAsync({ botId: bot.id, configId: config.id });
      toast.success(`${bot.name} deactivated`);
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
    } catch (error: any) {
      toast.error(error.message || "Failed to deactivate");
    }
    setConfirmAction(null);
  };

  const handleDeleteBot = async (bot: BotInstance) => {
    try {
      await deleteBotMutation.mutateAsync(bot.id);
      toast.success(`${bot.name} has been deleted`);
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      queryClient.invalidateQueries({ queryKey: ["active-config"] });
    } catch (error: any) {
      toast.error(error.message || "Failed to delete bot");
    }
    setConfirmAction(null);
  };

  const toggleSelectConfig = (configId: string) => {
    setSelectedConfigs(prev => 
      prev.includes(configId) ? prev.filter(id => id !== configId) : [...prev, configId]
    );
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Context Bar */}
      <Card className="border-border/50 bg-card/50">
        <CardContent className="py-4">
          <div className="flex flex-wrap items-center gap-4">
            {/* Environment Filter */}
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <div className="flex gap-1 rounded-lg bg-muted p-1 border border-border">
                {ENVIRONMENTS.map((env) => (
                  <button
                    key={env.value}
                    onClick={() => setEnvFilter(env.value)}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition-all ${
                      envFilter === env.value
                        ? `${env.bgColor} ${env.color} shadow-sm`
                        : "text-foreground hover:bg-muted-foreground/10"
                    }`}
                  >
                    {env.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-9 px-3 text-sm rounded-md border border-border bg-background focus:border-primary/60 transition-colors"
            >
              {STATUS_FILTERS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>

            {/* Search */}
            <div className="relative flex-1 min-w-[200px] max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search bots, symbols..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>

            <div className="flex-1" />

            {/* Bulk Actions */}
            {selectedConfigs.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">{selectedConfigs.length} selected</span>
                <Button variant="outline" size="sm">
                  <Pause className="h-4 w-4 mr-1" /> Pause All
                </Button>
                <Button variant="outline" size="sm">
                  <Download className="h-4 w-4 mr-1" /> Export
                </Button>
              </div>
            )}

            {/* Refresh */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => queryClient.invalidateQueries({ queryKey: ["bot-instances"] })}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <KPITile
          label="Running"
          value={kpis.running}
          icon={<Play className="h-4 w-4" />}
          color="text-green-400"
        />
        <KPITile
          label="Blocked"
          value={kpis.blocked}
          icon={<AlertTriangle className="h-4 w-4" />}
          color={kpis.blocked > 0 ? "text-red-400" : "text-muted-foreground"}
          alert={kpis.blocked > 0}
        />
        <KPITile
          label="Errors"
          value={kpis.errors}
          icon={<AlertTriangle className="h-4 w-4" />}
          color={kpis.errors > 0 ? "text-red-400" : "text-muted-foreground"}
          alert={kpis.errors > 0}
        />
        <KPITile
          label="Live Capital"
          value={formatCurrency(kpis.liveCapital)}
          icon={<DollarSign className="h-4 w-4" />}
          color="text-green-400"
        />
        <KPITile
          label="Paper Capital"
          value={formatCurrency(kpis.paperCapital)}
          icon={<DollarSign className="h-4 w-4" />}
          color="text-cyan-400"
        />
        <KPITile
          label="Total Trades"
          value={kpis.totalTrades.toLocaleString()}
          icon={<Activity className="h-4 w-4" />}
        />
        <KPITile
          label="Total Configs"
          value={fleetItems.length}
          icon={<Layers className="h-4 w-4" />}
          color="text-muted-foreground"
        />
      </div>

      {/* Fleet Table */}
      <Card className="border-border/50">
        <CardContent className="p-0">
          {fleetItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Bot className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">No Bots Found</h3>
              <p className="text-sm text-muted-foreground mb-4">
                {searchQuery || envFilter !== "all" || statusFilter !== "all"
                  ? "Try adjusting your filters"
                  : "Create your first trading bot to get started"}
              </p>
              <Button onClick={onCreateBot}>
                <Plus className="h-4 w-4 mr-2" />
                Create Bot
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border/50 bg-muted/30">
                    <th className="w-10 p-3">
                      <Checkbox
                        checked={selectedConfigs.length === fleetItems.length && fleetItems.length > 0}
                        onChange={() => {
                          if (selectedConfigs.length === fleetItems.length) {
                            setSelectedConfigs([]);
                          } else {
                            setSelectedConfigs(fleetItems.map(i => i.config.id));
                          }
                        }}
                      />
                    </th>
                    <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Bot</th>
                    <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Exchange</th>
                    <th className="text-left p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">State</th>
                    <th className="text-right p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Capital</th>
                    <th className="text-center p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Symbols</th>
                    <th className="text-right p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Trades</th>
                    <th className="text-right p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {fleetItems.map(({ bot, config }) => (
                    <tr
                      key={config.id}
                      className="hover:bg-muted/20 transition-colors cursor-pointer"
                      onClick={() => setDrawerConfig({ bot, config })}
                    >
                      <td className="p-3" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          checked={selectedConfigs.includes(config.id)}
                          onChange={() => toggleSelectConfig(config.id)}
                        />
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-3">
                          <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10 border border-primary/20">
                            <Bot className="h-4 w-4 text-primary" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{bot.name}</span>
                              <Badge className={`text-[10px] ${getMarketTypeBadge((bot as any).market_type || "perp")}`}>
                                {getMarketTypeLabel((bot as any).market_type || "perp")}
                              </Badge>
                              <Badge className={`text-[10px] ${getRoleBadge(bot.allocator_role)}`}>
                                {bot.allocator_role}
                              </Badge>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              {bot.template_name || "Custom strategy"}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className={getCombinedTradingModeBadgeClass(config.is_demo, config.environment)}>
                            {getCombinedTradingModeLabel(config.is_demo, config.environment)}
                          </Badge>
                          <div className="flex flex-col leading-tight">
                            <span className="text-sm capitalize">
                              {config.exchange_account_label || config.exchange || "exchange"}
                            </span>
                            {config.exchange_account_venue && (
                              <span className="text-[11px] text-muted-foreground uppercase">
                                {config.exchange_account_venue}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="p-3">
                        {config.state === "blocked" ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Badge className={`${getStateColor(config.state).bg} ${getStateColor(config.state).text} ${getStateColor(config.state).border} border cursor-help`}>
                                <AlertTriangle className="h-3 w-3 mr-1" />
                                blocked
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-xs">
                              <p className="font-semibold text-red-400 mb-1">Configuration Invalid</p>
                              <p className="text-xs">{config.last_error || "Click to edit and fix configuration issues"}</p>
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <Badge className={`${getStateColor(config.state).bg} ${getStateColor(config.state).text} ${getStateColor(config.state).border} border`}>
                            {config.state === "running" && <CircleDot className="h-3 w-3 mr-1 animate-pulse" />}
                            {config.state}
                          </Badge>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <span className="font-mono text-sm">
                          {formatCurrency(config.trading_capital_usd)}
                        </span>
                      </td>
                      <td className="p-3 text-center">
                        <span className="text-sm">{config.enabled_symbols?.length || 0}</span>
                      </td>
                      <td className="p-3 text-right">
                        <span className="font-mono text-sm">{config.trades_count || 0}</span>
                      </td>
                      <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          {config.is_active ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0"
                                  onClick={() => setConfirmAction({ type: "deactivate", config, bot })}
                                >
                                  <Power className="h-4 w-4 text-amber-400" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Deactivate</TooltipContent>
                            </Tooltip>
                          ) : (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 w-8 p-0"
                                  onClick={() => handleActivate(bot, config)}
                                  disabled={activateMutation.isPending}
                                >
                                  <Play className="h-4 w-4 text-green-400" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Activate</TooltipContent>
                            </Tooltip>
                          )}
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                                <MoreVertical className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => setDrawerConfig({ bot, config })}>
                                <Eye className="h-4 w-4 mr-2" /> View Details
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => onEditBot(bot)}>
                                <Edit className="h-4 w-4 mr-2" /> Edit Bot
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => onCloneBot(bot)}>
                                <Copy className="h-4 w-4 mr-2" /> Clone Bot
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem>
                                <Download className="h-4 w-4 mr-2" /> Export Config
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                className="text-red-400"
                                onClick={() => setConfirmAction({ type: "delete", bot })}
                              >
                                <Trash2 className="h-4 w-4 mr-2" /> Delete Bot
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bot Detail Drawer */}
      <BotDetailDrawer
        data={drawerConfig}
        onClose={() => setDrawerConfig(null)}
        onEdit={() => {
          if (drawerConfig) {
            onEditBot(drawerConfig.bot);
            setDrawerConfig(null);
          }
        }}
      />

      {/* Validation Error Modal */}
      <AlertDialog 
        open={validationModal.open} 
        onOpenChange={(open) => {
          if (!open) setValidationModal({ open: false });
        }}
      >
        <AlertDialogContent className="border-red-500/50 max-w-lg">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-red-500 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Configuration Blocked
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-4">
                <p>
                  <strong className="text-foreground">{validationModal.bot?.name}</strong> cannot start due to configuration issues:
                </p>
                
                {/* Errors */}
                {validationModal.result?.errors && validationModal.result.errors.length > 0 && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 space-y-2">
                    <p className="font-semibold text-red-400 text-sm flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4" />
                      Errors ({validationModal.result.errors.length})
                    </p>
                    <ul className="text-sm space-y-2 text-muted-foreground">
                      {validationModal.result.errors.map((issue, i) => (
                        <li key={i} className="flex flex-col gap-1">
                          <span className="text-red-300">{issue.message}</span>
                          {issue.detail && (
                            <span className="text-xs text-muted-foreground">{issue.detail}</span>
                          )}
                          {issue.suggestion && (
                            <span className="text-xs text-green-400">💡 {issue.suggestion}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                
                {/* Warnings */}
                {validationModal.result?.warnings && validationModal.result.warnings.length > 0 && (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
                    <p className="font-semibold text-amber-400 text-sm flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4" />
                      Warnings ({validationModal.result.warnings.length})
                    </p>
                    <ul className="text-sm space-y-1 text-muted-foreground list-disc list-inside">
                      {validationModal.result.warnings.map((issue, i) => (
                        <li key={i}>{issue.message}</li>
                      ))}
                    </ul>
                  </div>
                )}
                
                <p className="text-sm text-muted-foreground">
                  Edit the bot configuration to fix these issues before starting.
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Close</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (validationModal.bot) {
                  onEditBot(validationModal.bot);
                }
                setValidationModal({ open: false });
              }}
              className="bg-primary"
            >
              <Edit className="h-4 w-4 mr-2" />
              Edit Configuration
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirmation Dialogs */}
      <AlertDialog 
        open={!!confirmAction} 
        onOpenChange={(open) => {
          if (!open) {
            setConfirmAction(null);
            setDeleteConfirmText("");
          }
        }}
      >
        <AlertDialogContent className={confirmAction?.type === "delete" ? "border-red-500/50" : ""}>
          <AlertDialogHeader>
            <AlertDialogTitle className={confirmAction?.type === "delete" ? "text-red-500 flex items-center gap-2" : ""}>
              {confirmAction?.type === "delete" && <AlertTriangle className="h-5 w-5" />}
              {confirmAction?.type === "deactivate" && "Deactivate Bot Configuration?"}
              {confirmAction?.type === "delete" && "Delete Bot Permanently?"}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-4">
              {confirmAction?.type === "deactivate" && (
                  <p>
                    This will stop trading for <strong className="text-foreground">{confirmAction.bot?.name}</strong>.
                  Open positions will remain open.
                  </p>
              )}
              {confirmAction?.type === "delete" && (
                <>
                    <p>
                      You are about to delete <strong className="text-foreground">{confirmAction.bot?.name}</strong>.
                    </p>
                    
                    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 space-y-2">
                      <p className="font-semibold text-red-400 text-sm">This action will:</p>
                      <ul className="text-sm space-y-1 text-muted-foreground list-disc list-inside">
                        <li>Remove the bot and all its exchange configurations</li>
                        <li>Delete all symbol-specific settings</li>
                        <li>Release any symbol ownership locks</li>
                        <li>Remove budget allocations</li>
                      </ul>
                    </div>

                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
                      <p className="font-semibold text-amber-400 text-sm">What is preserved:</p>
                      <ul className="text-sm space-y-1 text-muted-foreground list-disc list-inside">
                        <li>Trade history and fills (for audit purposes)</li>
                        <li>Decision logs and performance records</li>
                        <li>Any open positions on the exchange (must be closed manually)</li>
                      </ul>
                    </div>

                    <div className="space-y-2 pt-2">
                      <p className="text-sm text-muted-foreground">
                        To confirm, type <span className="font-mono font-semibold text-foreground bg-muted px-1.5 py-0.5 rounded">{confirmAction.bot?.name}</span> below:
                      </p>
                      <Input
                        value={deleteConfirmText}
                        onChange={(e) => setDeleteConfirmText(e.target.value)}
                        placeholder="Type bot name to confirm"
                        className={cn(
                          "font-mono",
                          deleteConfirmText && deleteConfirmText !== confirmAction.bot?.name 
                            ? "border-red-500 focus-visible:ring-red-500" 
                            : deleteConfirmText === confirmAction.bot?.name 
                              ? "border-green-500 focus-visible:ring-green-500"
                              : ""
                        )}
                        autoComplete="off"
                        autoFocus
                      />
                      {deleteConfirmText && deleteConfirmText !== confirmAction.bot?.name && (
                        <p className="text-xs text-red-400">Name doesn't match</p>
                      )}
                    </div>
                </>
              )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteConfirmText("")}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmAction?.type === "deactivate" && confirmAction.bot && confirmAction.config) {
                  handleDeactivate(confirmAction.bot, confirmAction.config);
                } else if (confirmAction?.type === "delete" && confirmAction.bot) {
                  handleDeleteBot(confirmAction.bot);
                  setDeleteConfirmText("");
                }
              }}
              className={confirmAction?.type === "delete" ? "bg-red-600 hover:bg-red-700 disabled:bg-red-600/50" : ""}
              disabled={
                deleteBotMutation.isPending || 
                (confirmAction?.type === "delete" && deleteConfirmText !== confirmAction.bot?.name)
              }
            >
              {deleteBotMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : null}
              {confirmAction?.type === "deactivate" && "Deactivate"}
              {confirmAction?.type === "delete" && "Delete Permanently"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// KPI TILE
// ═══════════════════════════════════════════════════════════════

interface KPITileProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color?: string;
  alert?: boolean;
}

function KPITile({ label, value, icon, color = "text-muted-foreground", alert }: KPITileProps) {
  return (
    <Card className={`border-border/50 ${alert ? "border-red-500/50 bg-red-500/5" : ""}`}>
      <CardContent className="py-3 px-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
            <p className={`text-xl font-semibold ${color}`}>{value}</p>
          </div>
          <div className={`p-2 rounded-lg bg-white/5 ${color}`}>{icon}</div>
        </div>
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════
// BOT DETAIL DRAWER
// ═══════════════════════════════════════════════════════════════

interface BotDetailDrawerProps {
  data: { bot: BotInstance; config: BotExchangeConfig } | null;
  onClose: () => void;
  onEdit: () => void;
}

function BotDetailDrawer({ data, onClose, onEdit }: BotDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState("overview");

  if (!data) return null;
  const { bot, config } = data;

  return (
    <Sheet open={!!data} onOpenChange={() => onClose()}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader className="pb-4 border-b border-border/50">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 border border-primary/20">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1">
              <SheetTitle className="flex items-center gap-2">
                {bot.name}
                <Badge className={`text-[10px] ${getMarketTypeBadge((bot as any).market_type || "perp")}`}>
                  {getMarketTypeLabel((bot as any).market_type || "perp")}
                </Badge>
                <Badge className={`text-[10px] ${getRoleBadge(bot.allocator_role)}`}>
                  {bot.allocator_role}
                </Badge>
              </SheetTitle>
              <SheetDescription className="flex items-center gap-2 mt-1">
                <Badge variant="outline" className={getCombinedTradingModeBadgeClass(config.is_demo, config.environment)}>
                  {getCombinedTradingModeLabel(config.is_demo, config.environment)}
                </Badge>
                <span className="capitalize">{config.exchange}</span>
              </SheetDescription>
            </div>
            <Badge className={`${getStateColor(config.state).bg} ${getStateColor(config.state).text}`}>
              {config.state}
            </Badge>
          </div>
        </SheetHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="mt-4">
          <TabsList className="w-full">
            <TabsTrigger value="overview" className="flex-1 text-xs">Overview</TabsTrigger>
            <TabsTrigger value="logs" className="flex-1 text-xs">
              Logs
              {config.state === "error" && (
                <span className="ml-1 h-2 w-2 rounded-full bg-red-500 animate-pulse" />
              )}
            </TabsTrigger>
            <TabsTrigger value="config" className="flex-1 text-xs">Config</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-4 space-y-4">
            {/* Status */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-border/50 bg-card/50 p-3">
                <p className="text-xs text-muted-foreground mb-1">State</p>
                <p className={`font-semibold ${getStateColor(config.state).text}`}>{config.state}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-card/50 p-3">
                <p className="text-xs text-muted-foreground mb-1">Last Heartbeat</p>
                <p className="font-semibold text-sm">
                  {config.last_heartbeat_at ? new Date(config.last_heartbeat_at).toLocaleTimeString() : "—"}
                </p>
              </div>
            </div>

            {/* Capital */}
            <div className="rounded-lg border border-border/50 bg-card/50 p-4">
              <h4 className="text-sm font-medium mb-3 flex items-center gap-2">
                <DollarSign className="h-4 w-4 text-muted-foreground" />
                Capital Allocation
              </h4>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Trading Capital</span>
                  <span className="font-mono">{formatCurrency(config.trading_capital_usd)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Position Size</span>
                  <span className="font-mono">{config.risk_config?.positionSizePct || 5}%</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Max Leverage</span>
                  <span className="font-mono">{config.risk_config?.maxLeverage || 3}x</span>
                </div>
              </div>
            </div>

            {/* Symbols */}
            <div className="rounded-lg border border-border/50 bg-card/50 p-4">
              <h4 className="text-sm font-medium mb-3 flex items-center gap-2">
                <Layers className="h-4 w-4 text-muted-foreground" />
                Enabled Symbols ({config.enabled_symbols?.length || 0})
              </h4>
              <div className="flex flex-wrap gap-2">
                {config.enabled_symbols?.map(symbol => (
                  <Badge key={symbol} variant="outline" className="font-mono text-xs">
                    {symbol.replace("-USDT-SWAP", "")}
                  </Badge>
                ))}
              </div>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-border/50 bg-card/50 p-3">
                <p className="text-xs text-muted-foreground mb-1">Decisions</p>
                <p className="text-lg font-semibold">{config.decisions_count || 0}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-card/50 p-3">
                <p className="text-xs text-muted-foreground mb-1">Trades</p>
                <p className="text-lg font-semibold">{config.trades_count || 0}</p>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="logs" className="mt-4">
            <BotLogsPanel
              botId={bot.id}
              botName={bot.name}
              configId={config.id}
            />
          </TabsContent>

          <TabsContent value="config" className="mt-4 space-y-4">
            <div className="rounded-lg border border-border/50 bg-card/50 p-4">
              <h4 className="text-sm font-medium mb-3">Risk Configuration</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Position Size %</span>
                  <span className="font-mono">{config.risk_config?.positionSizePct}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Leverage</span>
                  <span className="font-mono">{config.risk_config?.maxLeverage}x</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Positions</span>
                  <span className="font-mono">{config.risk_config?.maxPositions || "—"}</span>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-border/50 bg-card/50 p-4">
              <h4 className="text-sm font-medium mb-3">Metadata</h4>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Config Version</span>
                  <span className="font-mono">v{config.config_version}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Created</span>
                  <span>{new Date(config.created_at).toLocaleDateString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Updated</span>
                  <span>{new Date(config.updated_at).toLocaleDateString()}</span>
                </div>
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <div className="mt-6 pt-4 border-t border-border/50 flex gap-2">
          <Button variant="outline" className="flex-1" onClick={onEdit}>
            <Edit className="h-4 w-4 mr-2" />
            Edit Bot
          </Button>
          <Button className="flex-1">
            <Eye className="h-4 w-4 mr-2" />
            Open Full View
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
