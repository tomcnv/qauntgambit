import { useState, useMemo, useEffect } from "react";
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Settings,
  Target,
  TrendingDown,
  DollarSign,
  Power,
  Loader2,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Separator } from "../../components/ui/separator";
import { Switch } from "../../components/ui/switch";
import { Label } from "../../components/ui/label";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
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
} from "../../components/ui/alert-dialog";
import toast from "react-hot-toast";
import { useDrawdownData, useRiskLimits, useUpdateRiskLimits, useDashboardRisk, useTradeHistory, useBotPositions, useOverviewData, useCloseAllOrphanedPositions, useCancelOrder, usePendingOrders } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { RunBar } from "../../components/run-bar";
import { emergencyStopBot } from "../../lib/api/control";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export default function RiskLimitsPage() {
  const [editSheetOpen, setEditSheetOpen] = useState(false);
  const { level: scopeLevel, exchangeAccountId, botId } = useScopeStore();
  const scopedExchangeAccountId = scopeLevel !== "fleet" ? exchangeAccountId ?? null : null;
  const scopedBotId = scopeLevel === "bot" ? botId ?? null : null;

  // Fetch real data
  const { data: drawdownData, isLoading: loadingDrawdown } = useDrawdownData(24, scopedExchangeAccountId, scopedBotId);
  const { data: riskLimitsData, isLoading: loadingLimits } = useRiskLimits();
  const { data: riskData, isLoading: loadingRisk } = useDashboardRisk({
    exchangeAccountId: scopedExchangeAccountId ?? undefined,
    botId: scopedBotId ?? undefined,
  });
  const { data: tradeHistoryData } = useTradeHistory({
    limit: 100,
    exchangeAccountId: scopedExchangeAccountId ?? undefined,
    botId: scopedBotId ?? undefined,
  });
  const { data: positionsData, isLoading: loadingPositions } = useBotPositions({
    exchangeAccountId: scopedExchangeAccountId ?? undefined,
    botId: scopedBotId ?? undefined,
  });
  const { data: overviewData } = useOverviewData({
    exchangeAccountId: scopedExchangeAccountId,
    botId: scopedBotId,
  });

  const isLoading = loadingDrawdown || loadingLimits || loadingRisk || loadingPositions;

  // Get real positions count
  const positions = positionsData?.data ?? positionsData?.positions ?? [];
  const openPositionsCount = positions.length;
  
  // Calculate total exposure from positions
  const totalExposureFromPositions = positions.reduce((sum: number, p: any) => {
    const notional = Math.abs(parseFloat(p.notional) || parseFloat(p.size) * parseFloat(p.mark_price) || 0);
    return sum + notional;
  }, 0);

  // Extract metrics from risk data or overview
  const botStatus = overviewData?.botStatus as any;
  const fastScalper = overviewData?.fastScalper as any;
  const botMetrics = botStatus?.metrics ?? fastScalper?.metrics ?? {};
  const metrics = riskData?.data ?? riskData ?? {};
  const engineLimits = metrics?.limits ?? {};
  const engineExposure = metrics?.exposure ?? {};
  const accountEquity = metrics?.account_equity ?? metrics?.accountEquity ?? 0;
  
  const currentDrawdown = botMetrics?.drawdown ?? metrics?.drawdown ?? drawdownData?.currentDrawdown ?? 0;
  const leverage = botMetrics?.leverage ?? metrics?.leverage ?? 1;
  const totalExposure = engineExposure?.total_usd ?? totalExposureFromPositions;

  const engineMaxExposureUsd = engineLimits?.max_total_exposure_pct && accountEquity
    ? (engineLimits.max_total_exposure_pct / 100) * accountEquity
    : null;
  const engineMaxLeverage = engineLimits?.max_leverage ?? engineLimits?.maxLeverage;
  const engineMaxPositions = engineLimits?.max_positions ?? engineLimits?.maxPositions;
  const engineMaxPositionSizeUsd = engineLimits?.max_position_size_usd ?? engineLimits?.maxPositionSizeUsd;

  // Calculate daily loss from trade history
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayTrades = (tradeHistoryData?.trades ?? []).filter((t: any) => 
    new Date(t.timestamp || t.exit_time) >= todayStart
  );
  const dailyPnl = todayTrades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0);
  const dailyLoss = dailyPnl < 0 ? Math.abs(dailyPnl) : 0;

  // Risk limits from API policy
  const policy = riskLimitsData?.policy ?? {};
  const dailyLossLimit = policy?.max_daily_loss_usd || 500;
  const maxLeverage = engineMaxLeverage ?? policy?.max_leverage ?? 10;
  const maxDrawdownLimit = policy?.circuit_breaker_loss_pct || 5;
  const maxPositions = engineMaxPositions ?? policy?.max_concurrent_positions ?? 5;
  const perTradeLossLimit = engineMaxPositionSizeUsd
    ?? (policy?.max_single_position_pct ? (totalExposure * policy.max_single_position_pct / 100) : 50);
  const maxExposure = engineMaxExposureUsd ?? policy?.total_capital_limit_usd ?? 10000;

  // Build risk limits array
  const riskLimits = useMemo(() => [
    { id: "daily-loss", label: "Daily Loss Limit", current: dailyLoss, limit: dailyLossLimit, unit: "$", enabled: true, critical: false },
    { id: "max-leverage", label: "Max Leverage", current: leverage, limit: maxLeverage, unit: "x", enabled: true, critical: false },
    { id: "max-positions", label: "Max Concurrent Positions", current: openPositionsCount, limit: maxPositions, unit: "", enabled: true, critical: false },
    { id: "max-drawdown", label: "Max Drawdown", current: currentDrawdown, limit: maxDrawdownLimit, unit: "%", enabled: true, critical: true },
    { id: "per-trade-loss", label: "Per-Trade Loss Limit", current: 0, limit: perTradeLossLimit, unit: "$", enabled: true, critical: false },
    { id: "total-exposure", label: "Total Exposure", current: totalExposure, limit: maxExposure, unit: "$", enabled: true, critical: false },
  ], [dailyLoss, dailyLossLimit, leverage, maxLeverage, openPositionsCount, maxPositions, currentDrawdown, maxDrawdownLimit, perTradeLossLimit, totalExposure, maxExposure]);

  // Kill switches from API policy.metadata or defaults
  const defaultKillSwitches = [
    { id: "daily-loss-kill", label: "Kill on daily loss limit", description: "Stop trading if daily loss exceeds limit", enabled: true },
    { id: "drawdown-kill", label: "Kill on max drawdown", description: "Emergency stop on excessive drawdown", enabled: true },
    { id: "connection-kill", label: "Kill on connection loss", description: "Flatten positions if exchange disconnects", enabled: false },
    { id: "time-kill", label: "Kill at end of day", description: "Close all positions at market close", enabled: false },
  ];
  const [killSwitches, setKillSwitches] = useState(defaultKillSwitches);
  const [hasSyncedKillSwitches, setHasSyncedKillSwitches] = useState(false);
  
  // Sync kill switches when policy loads (only once)
  useEffect(() => {
    if (policy?.metadata?.killSwitches && !hasSyncedKillSwitches && !loadingLimits) {
      setKillSwitches(policy.metadata.killSwitches);
      setHasSyncedKillSwitches(true);
    }
  }, [policy, hasSyncedKillSwitches, loadingLimits]);

  // Blocklist state - initialized from API
  const [blocklist, setBlocklist] = useState<{ symbol: string; reason: string; addedAt: string }[]>(
    riskData?.data?.blocklist ?? []
  );
  const [addSymbolOpen, setAddSymbolOpen] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [blockReason, setBlockReason] = useState("");
  
  // Editable limit values (for the configure panel)
  const [editableLimits, setEditableLimits] = useState({
    dailyLossLimit: 500,
    maxLeverage: 10,
    maxPositions: 5,
    maxDrawdown: 5,
    perTradeLoss: 50,
    maxExposure: 10000,
  });
  
  // Track if we've synced from policy to avoid repeated updates
  const [hasSyncedLimits, setHasSyncedLimits] = useState(false);
  
  // Sync editable limits when policy loads (only once)
  useEffect(() => {
    if (policy && !hasSyncedLimits && !loadingLimits) {
      setEditableLimits({
        dailyLossLimit: policy.max_daily_loss_usd || 500,
        maxLeverage: policy.max_leverage || 10,
        maxPositions: policy.max_concurrent_positions || 5,
        maxDrawdown: policy.circuit_breaker_loss_pct || 5,
        perTradeLoss: 50,
        maxExposure: policy.total_capital_limit_usd || 10000,
      });
      setHasSyncedLimits(true);
    }
  }, [policy, hasSyncedLimits, loadingLimits]);
  
  // Pending orders for cancel all
  const { data: pendingOrdersData } = usePendingOrders({
    exchangeAccountId: scopedExchangeAccountId,
    botId: scopedBotId,
  });
  const pendingOrders = pendingOrdersData?.orders ?? [];
  
  // Query client for invalidation
  const queryClient = useQueryClient();
  
  // Mutations for emergency actions
  const closeAllPositionsMutation = useCloseAllOrphanedPositions();
  const cancelOrderMutation = useCancelOrder();
  
  const emergencyStopMutation = useMutation({
    mutationFn: emergencyStopBot,
    onSuccess: () => {
      toast.success("Emergency stop executed - all positions closed, orders cancelled");
      queryClient.invalidateQueries({ queryKey: ["bot-positions"] });
      queryClient.invalidateQueries({ queryKey: ["pending-orders"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (error: any) => {
      toast.error(`Emergency stop failed: ${error.message || "Unknown error"}`);
    },
  });
  
  // Emergency action handlers
  const handleEmergencyStop = () => {
    emergencyStopMutation.mutate();
  };
  
  const handleFlattenAll = async () => {
    if (positions.length === 0) {
      toast.error("No positions to flatten");
      return;
    }
    try {
      await closeAllPositionsMutation.mutateAsync();
      toast.success(`Flattened ${positions.length} position(s)`);
    } catch (error: any) {
      toast.error(`Failed to flatten positions: ${error.message || "Unknown error"}`);
    }
  };
  
  const handleCancelAllOrders = async () => {
    if (pendingOrders.length === 0) {
      toast.error("No pending orders to cancel");
      return;
    }
    let cancelled = 0;
    let failed = 0;
    for (const order of pendingOrders) {
      try {
        await cancelOrderMutation.mutateAsync({ orderId: order.id, symbol: order.symbol });
        cancelled++;
      } catch {
        failed++;
      }
    }
    if (failed === 0) {
      toast.success(`Cancelled ${cancelled} order(s)`);
    } else {
      toast.error(`Cancelled ${cancelled}, failed ${failed}`);
    }
  };
  
  // Update risk limits mutation
  const updateRiskLimitsMutation = useUpdateRiskLimits();
  
  // Save configuration
  const handleSaveConfig = async () => {
    try {
      await updateRiskLimitsMutation.mutateAsync({
        // Map UI fields to API field names (snake_case)
        max_daily_loss_usd: editableLimits.dailyLossLimit,
        max_leverage: editableLimits.maxLeverage,
        max_concurrent_positions: editableLimits.maxPositions,
        circuit_breaker_loss_pct: editableLimits.maxDrawdown,
        total_capital_limit_usd: editableLimits.maxExposure,
        // Persist kill switches in metadata
        metadata: {
          ...(policy?.metadata || {}),
          killSwitches: killSwitches,
        },
      });
      toast.success("Risk limits saved successfully");
      setEditSheetOpen(false);
    } catch (error: any) {
      toast.error(error?.message || "Failed to save risk limits");
    }
  };

  const handleAddSymbol = () => {
    if (!newSymbol.trim()) {
      toast.error("Please enter a symbol");
      return;
    }
    const symbolUpper = newSymbol.trim().toUpperCase();
    if (blocklist.some(b => b.symbol === symbolUpper)) {
      toast.error("Symbol already blocked");
      return;
    }
    setBlocklist(prev => [
      ...prev,
      {
        symbol: symbolUpper,
        reason: blockReason.trim() || "Manual block",
        addedAt: new Date().toLocaleDateString(),
      }
    ]);
    setNewSymbol("");
    setBlockReason("");
    setAddSymbolOpen(false);
    toast.success(`${symbolUpper} added to blocklist`);
    // TODO: Persist to backend API
  };

  const handleRemoveSymbol = (symbol: string) => {
    setBlocklist(prev => prev.filter(b => b.symbol !== symbol));
    toast.success(`${symbol} removed from blocklist`);
    // TODO: Persist to backend API
  };

  const allLimitsOk = riskLimits.every(l => l.limit > 0 && (l.current / l.limit) < 0.9);

  const toggleKillSwitch = async (id: string) => {
    const updated = killSwitches.map((k: any) => 
      k.id === id ? { ...k, enabled: !k.enabled } : k
    );
    setKillSwitches(updated);
    
    try {
      await updateRiskLimitsMutation.mutateAsync({
        metadata: {
          ...(policy?.metadata || {}),
          killSwitches: updated,
        },
      });
      toast.success("Kill switch updated");
    } catch (error: any) {
      // Revert on error
      setKillSwitches(killSwitches);
      toast.error(error?.message || "Failed to update kill switch");
    }
  };

  // Determine risk status
  const riskStatus = useMemo(() => {
    const hasWarning = riskLimits.some(l => l.limit > 0 && (l.current / l.limit) > 0.8);
    const hasCritical = riskLimits.some(l => l.limit > 0 && (l.current / l.limit) > 0.95);
    if (hasCritical) return { label: "Critical", color: "text-red-500", bgColor: "border-red-500/30 bg-red-500/5" };
    if (hasWarning) return { label: "Warning", color: "text-amber-500", bgColor: "border-amber-500/30 bg-amber-500/5" };
    return { label: "Healthy", color: "text-emerald-500", bgColor: "border-emerald-500/30 bg-emerald-500/5" };
  }, [riskLimits]);

  return (
    <TooltipProvider>
      {/* Compact status bar - clicking takes you to Trading */}
      <RunBar />
      
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Limits & Guardrails</h1>
            <p className="text-sm text-muted-foreground">
              Live risk controls, kill switches, and blocklists
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            <Badge 
              variant="outline" 
              className={cn(
                "text-sm px-3 py-1",
                allLimitsOk 
                  ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-500" 
                  : "border-amber-500/50 bg-amber-500/10 text-amber-500"
              )}
            >
              {allLimitsOk ? (
                <><ShieldCheck className="h-4 w-4 mr-1.5" /> All Clear</>
              ) : (
                <><ShieldAlert className="h-4 w-4 mr-1.5" /> Limits Warning</>
              )}
            </Badge>
            <Button variant="outline" size="sm" onClick={() => setEditSheetOpen(true)}>
              <Settings className="h-4 w-4 mr-2" />
              Configure
            </Button>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className={riskStatus.bgColor}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Risk Status</span>
                {riskStatus.label === "Healthy" ? (
                  <ShieldCheck className="h-5 w-5 text-emerald-500" />
                ) : riskStatus.label === "Warning" ? (
                  <ShieldAlert className="h-5 w-5 text-amber-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
              </div>
              <p className={cn("text-2xl font-bold", riskStatus.color)}>{riskStatus.label}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {riskStatus.label === "Healthy" ? "All limits within bounds" : "Check limits below"}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Daily Loss Used</span>
                <DollarSign className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                ${dailyLoss.toFixed(2)} 
                <span className="text-sm font-normal text-muted-foreground"> / ${dailyLossLimit}</span>
              </p>
              <Progress value={dailyLossLimit > 0 ? (dailyLoss / dailyLossLimit) * 100 : 0} className="h-1.5 mt-2" />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Current Drawdown</span>
                <TrendingDown className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                {currentDrawdown.toFixed(2)}% 
                <span className="text-sm font-normal text-muted-foreground"> / {maxDrawdownLimit}%</span>
              </p>
              <Progress value={maxDrawdownLimit > 0 ? (currentDrawdown / maxDrawdownLimit) * 100 : 0} className="h-1.5 mt-2" />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-muted-foreground">Active Guardrails</span>
                <Shield className="h-4 w-4 text-muted-foreground" />
              </div>
              <p className="text-2xl font-bold">
                {riskLimits.filter(l => l.enabled).length} 
                <span className="text-sm font-normal text-muted-foreground"> / {riskLimits.length}</span>
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {killSwitches.filter((k: any) => k.enabled).length} kill switches armed
              </p>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Risk Limits */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Position & Loss Limits</CardTitle>
              <CardDescription>Real-time limit utilization</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {riskLimits.map((limit) => {
                const utilization = limit.limit > 0 ? (limit.current / limit.limit) * 100 : 0;
                const isWarning = utilization > 80;
                const isDanger = utilization > 95;

                return (
                  <div key={limit.id} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{limit.label}</span>
                        {limit.critical && (
                          <Tooltip>
                            <TooltipTrigger>
                              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                            </TooltipTrigger>
                            <TooltipContent>Critical limit - triggers kill switch</TooltipContent>
                          </Tooltip>
                        )}
                      </div>
                      <span className="text-sm font-mono">
                        {typeof limit.current === 'number' ? limit.current.toFixed(2) : limit.current}{limit.unit} / {limit.limit}{limit.unit}
                      </span>
                    </div>
                    <Progress 
                      value={utilization} 
                      className={cn(
                        "h-2",
                        isWarning && !isDanger && "[&>div]:bg-amber-500",
                        isDanger && "[&>div]:bg-red-500"
                      )}
                    />
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {/* Kill Switches */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-medium">Kill Switches</CardTitle>
                  <CardDescription>Automatic safety triggers</CardDescription>
                </div>
                <Badge variant="outline" className="text-xs">
                  {killSwitches.filter((k: any) => k.enabled).length} armed
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {killSwitches.map((rule: any) => (
                <div key={rule.id} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <Power className={cn("h-4 w-4", rule.enabled ? "text-emerald-500" : "text-muted-foreground")} />
                      <span className="text-sm font-medium">{rule.label}</span>
                    </div>
                    <p className="text-xs text-muted-foreground pl-6">{rule.description}</p>
                  </div>
                  <Switch checked={rule.enabled} onCheckedChange={() => toggleKillSwitch(rule.id)} />
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Emergency Actions & Blocklist */}
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Emergency Actions */}
          <Card className="border-red-500/20">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium text-red-500">Emergency Actions</CardTitle>
              <CardDescription>Manual intervention controls</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button 
                    variant="outline" 
                    className="w-full justify-start border-red-500/30 text-red-500 hover:bg-red-500/10"
                    disabled={emergencyStopMutation.isPending}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    {emergencyStopMutation.isPending ? "Stopping..." : "Emergency Stop All Trading"}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent className="sm:max-w-md">
                  <AlertDialogHeader>
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/10">
                      <Power className="h-7 w-7 text-red-500" />
                    </div>
                    <AlertDialogTitle className="text-center">Emergency Stop</AlertDialogTitle>
                    <AlertDialogDescription className="text-center">
                      This will immediately cancel all orders, close all positions, and stop the bot.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter className="sm:justify-center gap-2">
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction 
                      className="bg-red-500 hover:bg-red-600" 
                      onClick={handleEmergencyStop}
                    >
                      Confirm Stop
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>

              <Button 
                variant="outline" 
                className="w-full justify-start"
                onClick={handleFlattenAll}
                disabled={closeAllPositionsMutation.isPending || positions.length === 0}
              >
                <Target className="h-4 w-4 mr-2" />
                {closeAllPositionsMutation.isPending ? "Flattening..." : `Flatten All Positions (${positions.length})`}
              </Button>

              <Button 
                variant="outline" 
                className="w-full justify-start"
                onClick={handleCancelAllOrders}
                disabled={cancelOrderMutation.isPending || pendingOrders.length === 0}
              >
                <XCircle className="h-4 w-4 mr-2" />
                {cancelOrderMutation.isPending ? "Cancelling..." : `Cancel All Open Orders (${pendingOrders.length})`}
              </Button>
            </CardContent>
          </Card>

          {/* Symbol Blocklist */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base font-medium">Symbol Blocklist</CardTitle>
                  <CardDescription>Symbols excluded from trading</CardDescription>
                </div>
                <AlertDialog open={addSymbolOpen} onOpenChange={setAddSymbolOpen}>
                  <AlertDialogTrigger asChild>
                    <Button variant="outline" size="sm">Add Symbol</Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Add Symbol to Blocklist</AlertDialogTitle>
                      <AlertDialogDescription>
                        This symbol will be excluded from all trading activity.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <div className="space-y-4 py-4">
                      <div className="space-y-2">
                        <Label>Symbol</Label>
                        <Input 
                          placeholder="e.g., BTCUSDT" 
                          value={newSymbol}
                          onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                          className="font-mono"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Reason (optional)</Label>
                        <Input 
                          placeholder="e.g., High volatility, Low liquidity" 
                          value={blockReason}
                          onChange={(e) => setBlockReason(e.target.value)}
                        />
                      </div>
                    </div>
                    <AlertDialogFooter>
                      <AlertDialogCancel onClick={() => { setNewSymbol(""); setBlockReason(""); }}>
                        Cancel
                      </AlertDialogCancel>
                      <AlertDialogAction onClick={handleAddSymbol}>
                        Add to Blocklist
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </CardHeader>
            <CardContent>
              {blocklist.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
                  <CheckCircle2 className="h-8 w-8 mb-2 opacity-50" />
                  <p className="text-sm">No blocked symbols</p>
                  <p className="text-xs mt-1">Click "Add Symbol" to block a trading pair</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {blocklist.map((item) => (
                    <div key={item.symbol} className="flex items-center justify-between py-2 px-3 rounded-lg bg-muted/30">
                      <div>
                        <span className="font-mono font-medium">{item.symbol}</span>
                        <p className="text-xs text-muted-foreground">{item.reason} · Added {item.addedAt}</p>
                      </div>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button 
                            variant="ghost" 
                            size="sm" 
                            className="text-red-500 hover:text-red-600 hover:bg-red-500/10 h-7"
                            onClick={() => handleRemoveSymbol(item.symbol)}
                          >
                            <XCircle className="h-4 w-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Remove from blocklist</TooltipContent>
                      </Tooltip>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Edit Sheet */}
        <Sheet open={editSheetOpen} onOpenChange={setEditSheetOpen}>
          <SheetContent className="w-full sm:max-w-md overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Risk Configuration</SheetTitle>
              <SheetDescription>Edit risk limits and guardrails</SheetDescription>
            </SheetHeader>
            <div className="mt-6 space-y-6">
              <div className="space-y-2">
                <Label>Daily Loss Limit</Label>
                <div className="flex gap-2">
                  <Input 
                    type="number" 
                    value={editableLimits.dailyLossLimit} 
                    onChange={(e) => setEditableLimits(prev => ({ ...prev, dailyLossLimit: parseFloat(e.target.value) || 0 }))}
                    className="font-mono" 
                  />
                  <div className="flex items-center px-3 border rounded-md bg-muted text-sm text-muted-foreground">$</div>
                </div>
                <p className="text-xs text-muted-foreground">Max loss allowed per day before trading stops</p>
              </div>
              
              <div className="space-y-2">
                <Label>Max Leverage</Label>
                <div className="flex gap-2">
                  <Input 
                    type="number" 
                    value={editableLimits.maxLeverage}
                    onChange={(e) => setEditableLimits(prev => ({ ...prev, maxLeverage: parseFloat(e.target.value) || 1 }))}
                    className="font-mono" 
                    step="0.5"
                  />
                  <div className="flex items-center px-3 border rounded-md bg-muted text-sm text-muted-foreground">x</div>
                </div>
                <p className="text-xs text-muted-foreground">Maximum leverage across all positions</p>
              </div>
              
              <div className="space-y-2">
                <Label>Max Concurrent Positions</Label>
                <div className="flex gap-2">
                  <Input 
                    type="number" 
                    value={editableLimits.maxPositions}
                    onChange={(e) => setEditableLimits(prev => ({ ...prev, maxPositions: parseInt(e.target.value) || 1 }))}
                    className="font-mono" 
                    min="1"
                  />
                </div>
                <p className="text-xs text-muted-foreground">Max open positions at any time</p>
              </div>
              
              <div className="space-y-2">
                <Label>Max Drawdown</Label>
                <div className="flex gap-2">
                  <Input 
                    type="number" 
                    value={editableLimits.maxDrawdown}
                    onChange={(e) => setEditableLimits(prev => ({ ...prev, maxDrawdown: parseFloat(e.target.value) || 0 }))}
                    className="font-mono" 
                    step="0.5"
                  />
                  <div className="flex items-center px-3 border rounded-md bg-muted text-sm text-muted-foreground">%</div>
                </div>
                <p className="text-xs text-muted-foreground">Emergency stop if drawdown exceeds this</p>
              </div>
              
              <div className="space-y-2">
                <Label>Per-Trade Loss Limit</Label>
                <div className="flex gap-2">
                  <Input 
                    type="number" 
                    value={editableLimits.perTradeLoss}
                    onChange={(e) => setEditableLimits(prev => ({ ...prev, perTradeLoss: parseFloat(e.target.value) || 0 }))}
                    className="font-mono" 
                  />
                  <div className="flex items-center px-3 border rounded-md bg-muted text-sm text-muted-foreground">$</div>
                </div>
                <p className="text-xs text-muted-foreground">Max loss per individual trade</p>
              </div>
              
              <div className="space-y-2">
                <Label>Max Total Exposure</Label>
                <div className="flex gap-2">
                  <Input 
                    type="number" 
                    value={editableLimits.maxExposure}
                    onChange={(e) => setEditableLimits(prev => ({ ...prev, maxExposure: parseFloat(e.target.value) || 0 }))}
                    className="font-mono" 
                  />
                  <div className="flex items-center px-3 border rounded-md bg-muted text-sm text-muted-foreground">$</div>
                </div>
                <p className="text-xs text-muted-foreground">Max notional value of all positions</p>
              </div>
              
              <Separator />
              
              <div className="space-y-3">
                <Label className="text-base font-medium">Kill Switches</Label>
                {killSwitches.map((ks: any) => (
                  <div key={ks.id} className="flex items-center justify-between py-2">
                    <div>
                      <p className="text-sm font-medium">{ks.label}</p>
                      <p className="text-xs text-muted-foreground">{ks.description}</p>
                    </div>
                    <Switch 
                      checked={ks.enabled} 
                      onCheckedChange={() => toggleKillSwitch(ks.id)} 
                    />
                  </div>
                ))}
              </div>
              
              <Separator />
              
              <Button className="w-full" onClick={handleSaveConfig}>
                Save Changes
              </Button>
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </TooltipProvider>
  );
}
