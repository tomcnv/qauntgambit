import { useState, useMemo, useCallback } from "react";
import { TooltipProvider } from "../../components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Badge } from "../../components/ui/badge";
import {
  useOverviewData,
  useTradingSnapshot,
  usePendingOrders,
  useCancelOrder,
  useReplaceOrder,
  useActiveBot,
  useTradeHistory,
  useBotInstances,
  useLiveStatus,
  useExecutionStats,
  useBotPositions,
} from "../../lib/api/hooks";
import { TradeInspectorDrawer } from "../../components/trade-history/TradeInspectorDrawer";
import { useWebSocketContext } from "../../lib/websocket/WebSocketProvider";
import toast from "react-hot-toast";
import { useScopeStore } from "../../store/scope-store";
import { useExchangeAccounts } from "../../lib/api/exchange-accounts-hooks";
import { RunBar } from "../../components/run-bar";

// New modular components
import {
  StatusStrip,
  useLiveStatus as useStatusData,
  OpsKPICards,
  useOpsMetrics,
  SymbolStrip,
  useSymbolStats,
  LiveTape,
  WhyNoTrades,
  useWhyNoTrades,
  OrderAttempts,
  useOrderAttempts,
  RejectedSignals,
  useRejectedSignals,
  BlockingIntents,
  LiveStatus,
  OpsMetrics,
  LossPreventionPanel,
  SentimentPanel,
  ParamSuggestionsPanel,
  SpotPriceChart,
} from "../../components/live";
import { KillSwitchPanel } from "../../components/quant";
import { cn, formatQuantity } from "../../lib/utils";

export default function LiveTradingPage() {
  // Scope management
  const { level: scopeLevel, exchangeAccountId, exchangeAccountName, botId, botName } = useScopeStore();
  
  // Fetch exchange accounts and bot instances for header
  const { data: exchangeAccounts = [] } = useExchangeAccounts();
  const { data: botInstancesData } = useBotInstances();
  const bots = (botInstancesData as any)?.bots || [];
  
  // Find selected exchange account
  const selectedAccount = (exchangeAccounts as any[]).find((acc: any) => acc.id === exchangeAccountId);
  
  // Find bot connected to the selected exchange
  const botForExchange = bots.find((bot: any) => 
    bot.exchangeConfigs?.some((config: any) => config.exchange_account_id === exchangeAccountId)
  );
  const scopedBotId = botId || botForExchange?.id || undefined;

  // Core data fetching
  const { data: overviewData } = useOverviewData({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId : null,
    botId: scopeLevel !== 'fleet' ? scopedBotId ?? null : null,
  });

  // Live status for StatusStrip and OpsKPICards
  const { data: liveStatusData } = useLiveStatus({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId : null,
    botId: scopeLevel !== 'fleet' ? scopedBotId ?? null : null,
  });
  
  // Execution stats for latency data
  const { data: executionData } = useExecutionStats({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId || undefined : undefined,
    botId: scopeLevel !== 'fleet' ? scopedBotId || undefined : undefined,
  });
  
  // Trade history for fills
  const tradeHistoryParams = useMemo(() => ({
    limit: 500,
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId || undefined : undefined,
    botId: scopeLevel !== 'fleet' ? scopedBotId || undefined : undefined,
  }), [scopeLevel, exchangeAccountId, scopedBotId]);
  
  const { data: tradeHistoryData } = useTradeHistory(tradeHistoryParams);
  
  const { data: positionsData } = useBotPositions({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId || undefined : undefined,
    botId: scopeLevel !== 'fleet' ? scopedBotId || undefined : undefined,
  });
  const livePositions = positionsData?.data || positionsData?.positions || [];
  
  // Pending orders - scoped
  const { data: pendingOrdersResp } = usePendingOrders({
    exchangeAccountId: scopeLevel !== 'fleet' ? exchangeAccountId : null,
    botId: scopeLevel !== 'fleet' ? scopedBotId ?? null : null,
  });
  
  const { data: activeBotData } = useActiveBot();
  const cancelOrderMutation = useCancelOrder();
  const replaceOrderMutation = useReplaceOrder();
  const { isConnected: wsConnected } = useWebSocketContext();
  
  // UI State
  const [replaceOrderDraft, setReplaceOrderDraft] = useState<any | null>(null);
  const [replacePrice, setReplacePrice] = useState<string>("");
  const [replaceSize, setReplaceSize] = useState<string>("");
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [orderErrors, setOrderErrors] = useState<Record<string, string>>({});
  const [selectedFill, setSelectedFill] = useState<any | null>(null);
  const [selectedSymbolFilter, setSelectedSymbolFilter] = useState<string>("");

  const resolveTradePnl = useCallback((trade: any) => {
    const toNum = (value: any) => {
      const num = Number(value);
      return Number.isFinite(num) ? num : 0;
    };
    const netRaw = trade?.net_pnl ?? trade?.netPnl;
    const grossRaw = trade?.gross_pnl ?? trade?.grossPnl;
    const feesRaw = trade?.total_fees_usd ?? trade?.totalFees ?? trade?.fees ?? trade?.fee;
    const fees = toNum(feesRaw);
    const net = netRaw != null ? toNum(netRaw) : (grossRaw != null ? toNum(grossRaw) - fees : toNum(trade?.pnl));
    const gross = grossRaw != null ? toNum(grossRaw) : (netRaw != null ? net + fees : toNum(trade?.pnl) + fees);
    return { net, gross, fees };
  }, []);

  // Process data for components
  const fills = useMemo(() => {
    const trades = tradeHistoryData?.trades || [];
    return trades.slice(0, 500).map((t: any) => {
      const qty = parseFloat(t.quantity || t.filled_qty || t.size || 0);
      const price = parseFloat(t.exit_price || t.price || t.entry_price || 0);
      const { net, fees } = resolveTradePnl(t);
      const pnl = net;
      const storedFee = fees;
      
      // Calculate realistic fee if stored fee seems invalid
      // (0 or suspiciously equal to PnL indicates bad data)
      // Use 0.05% as typical taker fee for paper trading
      const tradeValue = qty * price;
      const calculatedFee = tradeValue * 0.0005; // 0.05% fee
      const fee = (storedFee === 0 || Math.abs(storedFee - Math.abs(pnl)) < 0.0001) 
        ? calculatedFee 
        : storedFee;
      
      return {
        id: t.id || t.trade_id,
        time: t.time || new Date(t.timestamp || t.created_at).toLocaleTimeString(),
        timestamp: new Date(t.timestamp || t.created_at || t.time).getTime(),
        symbol: t.symbol,
        side: (t.side || "").toUpperCase(),
        quantity: qty,
        entryPrice: t.entry_price || t.price,
        exitPrice: t.exit_price,
        pnl: pnl,
        stopLoss: t.stop_loss,
        takeProfit: t.take_profit,
        strategy: t.strategy,
        latency: t.latency_ms || t.fill_time_ms || t.latency,
        slippage: t.slippage_bps || t.slippage,
        fee: fee,
        orderType: t.order_type,
        decisionId: t.decision_id,
        reconciled: t.reconciled,
      };
    });
  }, [tradeHistoryData, resolveTradePnl]);

  const orders = useMemo(() => {
    const pending = pendingOrdersResp?.orders || pendingOrdersResp || [];
    if (!Array.isArray(pending)) return [];
    return pending.map((o: any) => ({
      id: o.id || o.order_id,
      time: o.time || new Date(o.timestamp || o.created_at).toLocaleTimeString(),
      timestamp: new Date(o.timestamp || o.created_at || o.time).getTime(),
      symbol: o.symbol,
      side: (o.side || "").toUpperCase(),
      type: o.type || o.order_type,
      quantity: o.quantity || o.qty || o.size,
      price: o.price,
      status: o.status,
    }));
  }, [pendingOrdersResp]);

  // API-provided top symbols (more accurate PnL than calculated from fills)
  const apiTopSymbols = useMemo(() => {
    const symbols = liveStatusData?.topSymbols;
    if (!symbols || symbols.length === 0) return undefined;
    return symbols.map((s: any) => ({
      symbol: s.symbol,
      count: s.signals || 0,
      pnl: s.pnl || 0,
      avgSlip: s.slippage || 0,
    }));
  }, [liveStatusData?.topSymbols]);

  // API-provided latency stats (from execution quality metrics)
  const apiLatency = useMemo(() => {
    const quality = executionData?.data?.quality?.overall ?? executionData?.data?.quality?.recent;
    if (!quality) return undefined;
    return {
      p50: quality.ack_to_fill_p50 ?? null,
      p95: quality.ack_to_fill_p95 ?? null,
      p99: quality.ack_to_fill_p99 ?? null,
      avg: quality.avg_execution_time_ms ?? null,
    };
  }, [executionData?.data?.quality]);

  // Build status from live status endpoint
  const liveStatus: LiveStatus = useMemo(() => {
    const data = liveStatusData || {};
    return {
      heartbeat: {
        status: data.heartbeat?.status || (wsConnected ? "ok" : "stale"),
        lastTickMs: data.heartbeat?.lastTickTime ? new Date(data.heartbeat.lastTickTime).getTime() : 0,
        ageSeconds: data.heartbeat?.ageSeconds ?? 999,
      },
      websocket: {
        market: wsConnected,
        orders: wsConnected,
        positions: wsConnected,
      },
      lastDecision: {
        status: data.lastDecision?.approved === false 
          ? "rejected" 
          : data.lastDecision?.approved === true 
            ? "approved" 
            : "none",
        reason: data.lastDecision?.reason,
        timestamp: data.lastDecision?.time,
        symbol: data.lastDecision?.symbol,
      },
      lastOrder: {
        status: data.lastOrder?.status || "none",
        latencyMs: data.lastOrder?.latency,
        timestamp: data.lastOrder?.time,
        symbol: data.lastOrder?.symbol,
      },
      riskState: {
        status: data.riskState?.status || "ok",
        guardrail: data.riskState?.guardrail,
        pausedBy: data.riskState?.pausedBy,
      },
      dataQuality: {
        score: data.dataQuality?.score ?? 100,
        gapCount: data.dataQuality?.gapCount ?? 0,
        staleSymbols: data.dataQuality?.staleSymbols ?? [],
      },
    };
  }, [liveStatusData, wsConnected]);

  // Build ops metrics - use local data as primary source for reliability
  const opsMetrics: OpsMetrics = useMemo(() => {
    const data = liveStatusData || {};
    const paperStats = tradeHistoryData?.stats?.paperStats;
    
    // Calculate exposure from positions (same logic as overview page)
    const netExposure = livePositions.reduce((sum: number, pos: any) => {
      const qty = parseFloat(pos.quantity || pos.size || 0) || 0;
      const price = parseFloat(pos.mark_price || pos.current_price || pos.markPrice || pos.entry_price || pos.entryPrice || 0) || 0;
      const notional = Math.abs(qty * price);
      const side = (pos.side || '').toUpperCase();
      // LONG/BUY = positive, everything else (SHORT/SELL) = negative
      const signed = (side === 'LONG' || side === 'BUY') ? notional : -notional;
      return sum + signed;
    }, 0);
    const grossExposure = livePositions.reduce((sum: number, pos: any) => {
      const qty = parseFloat(pos.quantity || pos.size || 0) || 0;
      const price = parseFloat(pos.mark_price || pos.current_price || pos.markPrice || pos.entry_price || pos.entryPrice || 0) || 0;
      return sum + Math.abs(qty * price);
    }, 0);
    
    // Calculate slippage from fills
    const slippages = fills.map(f => Math.abs(f.slippage || 0)).filter(s => s > 0).sort((a, b) => a - b);
    const slippageP50 = slippages.length > 0 ? slippages[Math.floor(slippages.length * 0.5)] : 0;
    const slippageP95 = slippages.length > 0 ? slippages[Math.floor(slippages.length * 0.95)] : 0;
    const slippageAvg = slippages.length > 0 ? slippages.reduce((a, b) => a + b, 0) / slippages.length : 0;
    
    // Calculate P&L from TODAY's fills only (consistent with overview page)
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayFills = fills.filter((f: any) => new Date(f.timestamp || f.time) >= todayStart);
    
    const todayRealizedPnl = todayFills.reduce((sum: number, f: any) => sum + parseFloat(f.pnl || 0), 0);
    const todayFees = todayFills.reduce((sum: number, f: any) => sum + Math.abs(parseFloat(f.fee || 0)), 0);
    const unrealizedPnl = livePositions.reduce((sum: number, p: any) => 
      sum + parseFloat(p.unrealizedPnl || p.unrealized_pnl || p.pnl || 0), 0);
    
    // Use today's calculated P&L (matching overview page timeframe)
    const realizedPnl = todayRealizedPnl;
    const totalFees = todayFees;
    const todayTradesCount = todayFills.length;
    
    // Calculate oldest order age (excluding SL/TP protection orders which are expected to be old)
    let oldestOrderAge = 0;
    const now = Date.now();
    const protectionOrderTypes = ['STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT', 'stop_loss', 'take_profit', 'trailing_stop', 'stop_limit'];
    orders.forEach((o: any) => {
      // Skip protection orders - they're designed to sit open until triggered
      const orderType = (o.type || '').toUpperCase();
      if (protectionOrderTypes.some(t => orderType.includes(t.toUpperCase()))) return;
      
      const orderTime = new Date(o.timestamp || o.time).getTime();
      if (orderTime > 0) {
        const age = (now - orderTime) / 1000;
        if (age > oldestOrderAge) oldestOrderAge = age;
      }
    });

    return {
      exposure: {
        // Always use our calculated exposure from livePositions (consistent with overview page)
        net: netExposure,
        gross: grossExposure,
        maxAllowedPct: 100,
        currentPct: grossExposure > 0 ? (grossExposure / 10000) * 100 : 0, // Assume 10k max
      },
      pendingOrders: {
        count: data.pendingOrders?.count ?? orders.length,
        oldestAgeSeconds: data.pendingOrders?.oldestAgeSeconds ?? Math.floor(oldestOrderAge),
      },
      rejectRate: {
        last5m: data.rejectRate?.last5m ?? 0,
        last1h: data.rejectRate?.last1h ?? 0,
        topReason: data.rejectRate?.topReason ?? "",
        topReasonCount: data.rejectRate?.topReasonCount ?? 0,
      },
      slippage: {
        p50: data.slippage?.p50 ?? slippageP50,
        p95: data.slippage?.p95 ?? slippageP95,
        avg: data.slippage?.avg ?? slippageAvg,
      },
      pnl: {
        realized: realizedPnl,
        unrealized: data.pnl?.unrealized ?? unrealizedPnl,
        fees: totalFees,
        net: realizedPnl + unrealizedPnl - totalFees, // Today's net P&L
        tradesCount: todayTradesCount, // Today's trade count
      },
    };
  }, [liveStatusData, orders, fills, livePositions, tradeHistoryData]);

  // Symbol stats for the symbol strip - merge realized PnL from fills with unrealized PnL from positions
  const baseSymbolStats = useSymbolStats(fills);
  const symbolStats = useMemo(() => {
    // Start with fill-based stats
    const statsMap = new Map(baseSymbolStats.map(s => [s.symbol, { ...s }]));
    
    // Add unrealized PnL from open positions
    livePositions.forEach((pos: any) => {
      const symbol = pos.symbol;
      const unrealizedPnl = parseFloat(pos.unrealizedPnl || pos.unrealized_pnl || 0) || 0;
      
      const existing = statsMap.get(symbol);
      if (existing) {
        // Add unrealized PnL to existing realized PnL
        existing.netPnl += unrealizedPnl;
      } else {
        // Position exists but no fills yet - create new entry
        statsMap.set(symbol, {
          symbol,
          netPnl: unrealizedPnl,
          fillsCount: 0,
          avgSlippage: 0,
          avgLatency: 0,
          volume: Math.abs(parseFloat(pos.size || pos.quantity || 0)) * parseFloat(pos.entry_price || pos.entryPrice || 0),
        });
      }
    });
    
    return Array.from(statsMap.values());
  }, [baseSymbolStats, livePositions]);

  // Check if this is a paper trading account
  const isPaperMode = selectedAccount?.environment === 'paper';
  
  // Check if bot is actively running (based on backend heartbeat/status)
  const isBotRunning =
    liveStatusData?.botStatus === 'running' ||
    liveStatusData?.botStatus === 'slow' ||
    overviewData?.botStatus?.trading?.isActive === true ||
    overviewData?.fastScalper?.status === 'running';
  
  // Order attempts for visibility into trading decisions
  const { data: orderAttemptsData, refetch: refetchOrderAttempts, isLoading: isLoadingAttempts } = useOrderAttempts(
    scopedBotId,
    { refetchInterval: 5000 }
  );
  
  // Rejected signals for visibility into why signals are being rejected
  const { data: rejectedSignalsData, refetch: refetchRejectedSignals, isLoading: isLoadingRejections } = useRejectedSignals(
    scopedBotId,
    { refetchInterval: 5000 }
  );
  const isFunnelLive = liveStatusData?.funnel?.isLive ?? false;
  
  // Why no trades data - calculate exposure directly from positions to avoid timing issues
  const whyNoTrades = useMemo(() => {
    const data = liveStatusData || {};
    
    // Calculate gross exposure directly from positions (same as overview page)
    const positionExposure = livePositions.reduce((sum: number, pos: any) => {
      const qty = parseFloat(pos.quantity || pos.size || 0) || 0;
      const price = parseFloat(pos.mark_price || pos.current_price || pos.markPrice || pos.entry_price || pos.entryPrice || 0) || 0;
      return sum + Math.abs(qty * price);
    }, 0);
    
    // Use backend funnel data but ensure actual fills count is used as authoritative source
    // Funnel flow: Evaluated → Gated → Approved → Ordered → Filled
    // Each earlier step must be >= later step
    const actualFillCount = fills.length;
    const filled = Math.max(data.funnel?.filled ?? 0, actualFillCount);
    const ordered = Math.max(data.funnel?.ordered ?? 0, filled);
    const approved = Math.max(data.funnel?.approved ?? 0, ordered);
    const gated = Math.max(data.funnel?.gated ?? 0, approved);
    const evaluated = Math.max(data.funnel?.evaluated ?? 0, gated);
    
    return {
      funnel: {
        evaluated,
        gated,
        approved,
        ordered,
        filled,
        isLive: isFunnelLive,
      },
      gates: [
        {
          name: "Spread",
          blocking: data.gates?.spread?.blocking ?? false,
          current: data.gates?.spread?.current ?? (isPaperMode ? 0.01 : 0.02),
          threshold: data.gates?.spread?.threshold ?? 0.1,
          unit: "%",
        },
        {
          name: "Depth",
          blocking: data.gates?.depth?.blocking ?? false,
          current: data.gates?.depth?.current ?? (isPaperMode ? 50000 : 5000),
          threshold: data.gates?.depth?.threshold ?? 1000,
          unit: "$",
        },
        {
          name: "Volatility",
          blocking: data.gates?.volatility?.blocking ?? false,
          current: data.gates?.volatility?.current ?? (isPaperMode ? 0.5 : 1.5),
          threshold: data.gates?.volatility?.threshold ?? 5,
          unit: "%",
        },
        {
          name: "Exposure",
          blocking: data.gates?.exposure?.blocking ?? (positionExposure > 10000),
          current: data.gates?.exposure?.current ?? positionExposure,
          threshold: data.gates?.exposure?.threshold ?? 10000,
          unit: "$",
        },
      ],
      decisionsPerSec: data.decisionsPerSec ?? 0,
      lastTradeAgo: fills[0]?.timestamp 
        ? Math.floor((Date.now() - fills[0].timestamp) / 1000)
        : undefined,
      isPaper: isPaperMode,
      isBotRunning: isBotRunning,
    };
  }, [liveStatusData, fills, livePositions, isPaperMode, isBotRunning, isFunnelLive]);

  // Bot state
  const botStatus = overviewData?.botStatus as any;
  const isTradingActive = botStatus?.trading?.isActive ?? false;
  const platformStatus = botStatus?.platform?.status ?? "stopped";
  
  const getBotState = (): "running" | "paused" | "degraded" | "stopped" => {
    if (isTradingActive) return "running";
    if (platformStatus === "degraded" || platformStatus === "error") return "degraded";
    if (platformStatus === "paused" || platformStatus === "stopped") return "paused";
    return "stopped";
  };

  // Event handlers
  const handleRowClick = (type: string, item: any) => {
    if (type === "fill") {
      setSelectedFill(item);
    }
  };

  const handleCancelOrder = async (order: any) => {
    const orderId = order.id || order.order_id;
    setCancelingId(orderId);
    setOrderErrors((prev) => ({ ...prev, [orderId]: "" }));
    try {
      await cancelOrderMutation.mutateAsync({ orderId, symbol: order.symbol });
      toast.success("Order canceled");
    } catch (e: any) {
      setOrderErrors((prev) => ({ ...prev, [orderId]: e.message || "Cancel failed" }));
      toast.error("Failed to cancel order");
    } finally {
      setCancelingId(null);
    }
  };

  const openReplaceOrder = (order: any) => {
    setReplaceOrderDraft(order);
    setReplacePrice(String(order.price ?? ""));
    setReplaceSize(String(order.quantity ?? order.qty ?? ""));
  };

  const closeReplaceDialog = () => {
    setReplaceOrderDraft(null);
    setReplacePrice("");
    setReplaceSize("");
  };

  const handleReplace = async () => {
    if (!replaceOrderDraft) return;
    const orderId = replaceOrderDraft.id || replaceOrderDraft.order_id;
    setReplacingId(orderId);
    try {
      await replaceOrderMutation.mutateAsync({
        orderId,
        symbol: replaceOrderDraft.symbol,
        price: parseFloat(replacePrice),
        quantity: parseFloat(replaceSize),
      });
      toast.success("Order replaced");
      closeReplaceDialog();
    } catch (e: any) {
      toast.error(e.message || "Replace failed");
    } finally {
      setReplacingId(null);
    }
  };

  const handleBotRun = async () => {
    try {
      await apiFetch("/bot/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "start" }),
      });
      toast.success("Bot started");
    } catch (e) {
      toast.error("Failed to start bot");
    }
  };

  const handleBotPause = async () => {
    try {
      await apiFetch("/bot/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "pause" }),
      });
      toast.success("Bot paused");
    } catch (e) {
      toast.error("Failed to pause bot");
    }
  };

  const handleBotHalt = async (options: { cancelOrders: boolean; closePositions: boolean }) => {
    try {
      await apiFetch("/bot/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          action: "halt",
          cancelOrders: options.cancelOrders,
          closePositions: options.closePositions,
        }),
      });
      toast.success("Bot halted");
    } catch (e) {
      toast.error("Failed to halt bot");
    }
  };

  const handleCancelAllOrders = async () => {
    try {
      await apiFetch("/dashboard/cancel-all-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ exchangeAccountId, botId }),
      });
      toast.success("All orders canceled");
    } catch (e) {
      toast.error("Failed to cancel orders");
    }
  };

  const handleFlattenAll = async () => {
    try {
      await apiFetch("/dashboard/close-all-positions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ exchangeAccountId, botId }),
      });
      toast.success("All positions closed");
    } catch (e) {
      toast.error("Failed to close positions");
    }
  };

  const handleKPICardClick = (cardType: string) => {
    // Could scroll to relevant section or filter the tape
    console.log("KPI card clicked:", cardType);
  };

  const handleOpenReplay = (fill: { symbol?: string; timestamp?: string | number; id?: string; decisionId?: string }) => {
    // Navigate to Replay Studio with trade context
    const params = new URLSearchParams();
    if (fill.symbol) params.set("symbol", fill.symbol);
    if (fill.timestamp) {
      // Convert timestamp to ISO string if it's a number
      const timeStr = typeof fill.timestamp === "number" 
        ? new Date(fill.timestamp).toISOString() 
        : fill.timestamp;
      params.set("time", timeStr);
    }
    if (fill.id) params.set("tradeId", fill.id);
    window.open(`/analysis/replay?${params.toString()}`, "_blank");
  };

  // Determine if we should show "why no trades" panel
  const showWhyNoTrades = fills.length === 0 || (fills.length > 0 && fills[0].timestamp < Date.now() - 300000);

  return (
    <TooltipProvider>
      {/* Sticky Run Bar */}
      <RunBar />
      
      <div className="flex flex-col min-h-full">
        {/* Main Content */}
        <div className="flex-1 p-6 space-y-6 max-w-[1600px] mx-auto w-full">
          
          {/* Page header */}
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Live</h1>
            <p className="text-sm text-muted-foreground">Real-time execution monitoring and control</p>
          </div>

          {/* Status Strip + Kill Switch */}
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <StatusStrip status={liveStatus} className="flex-1" />
            <KillSwitchPanel compact />
          </div>

          {/* Spot Price Chart — shown when bot is spot market type */}
          {(() => {
            const selectedBot = bots.find((b: any) => b.id === botId);
            const isSpot = selectedBot?.market_type === 'spot';
            if (!isSpot) return null;
            const chartSymbols = liveStatusData?.topSymbols?.map((s: any) => s.symbol)
              || [...new Set(livePositions.map((p: any) => p.symbol))]
              || [];
            const symbols = chartSymbols.length > 0 ? chartSymbols : ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'];
            return (
              <SpotPriceChart
                symbols={symbols}
                positions={livePositions}
                defaultSymbol={selectedSymbolFilter || undefined}
                onSymbolChange={setSelectedSymbolFilter}
              />
            );
          })()}

          {/* AI Sentiment */}
          <SentimentPanel sentiment={liveStatusData?.sentiment ?? {}} />

          {/* AI Param Tuner Suggestions */}
          {liveStatusData?.paramSuggestions && (
            <ParamSuggestionsPanel data={liveStatusData.paramSuggestions} />
          )}

          {/* Ops KPI Cards */}
          <OpsKPICards 
            metrics={opsMetrics} 
            onCardClick={handleKPICardClick}
          />

          {/* Symbol Strip */}
          {symbolStats.length > 0 && (
            <SymbolStrip
              symbols={symbolStats}
              selectedSymbol={selectedSymbolFilter}
              onSymbolClick={setSelectedSymbolFilter}
            />
          )}

          {/* Why No Trades Panel - show when quiet */}
          {showWhyNoTrades && (
            <WhyNoTrades
              funnel={whyNoTrades.funnel}
              gates={whyNoTrades.gates}
              decisionsPerSec={whyNoTrades.decisionsPerSec}
              lastTradeAgo={whyNoTrades.lastTradeAgo}
              isPaper={isPaperMode}
              isBotRunning={isBotRunning}
            />
          )}

          {/* Loss Prevention Panel - Shows metrics on rejected signals and estimated losses avoided */}
          {scopedBotId && (
            <LossPreventionPanel
              botId={scopedBotId}
              windowHours={24}
            />
          )}

          {/* Rejected Signals Panel - Shows why signals are being rejected */}
          {scopedBotId && (rejectedSignalsData?.rejections?.length > 0 || isLoadingRejections) && (
            <RejectedSignals
              rejections={rejectedSignalsData?.rejections || []}
              stats={rejectedSignalsData?.stats || {
                total_rejections: 0,
                reason_counts: {},
                stage_counts: {},
                by_symbol: {},
              }}
              isLoading={isLoadingRejections}
              onRefresh={refetchRejectedSignals}
            />
          )}

          {/* Order Attempts Panel - Always show when bot scoped to track all trading attempts */}
          {scopedBotId && (
            <OrderAttempts
              attempts={orderAttemptsData?.attempts || []}
              stats={orderAttemptsData?.stats || {
                total_attempts: 0,
                total_filled: 0,
                total_rejected: 0,
                total_failed: 0,
                rejection_reasons: {},
                by_symbol: {},
                by_profile: {},
              }}
              isLoading={isLoadingAttempts}
              onRefresh={refetchOrderAttempts}
            />
          )}

          {/* Blocking Intents - shows when there are pending/submitted intents blocking trades */}
          {scopedBotId && (
            <BlockingIntents botId={scopedBotId} />
          )}

          {/* Live Tape */}
          <LiveTape
            fills={fills}
            orders={orders}
            cancels={[]}
            rejects={[]}
            positions={livePositions}
            onRowClick={handleRowClick}
            onCancel={handleCancelOrder}
            onReplace={openReplaceOrder}
            cancelingId={cancelingId}
            replacingId={replacingId}
            orderErrors={orderErrors}
            onOpenReplay={handleOpenReplay}
            apiTopSymbols={apiTopSymbols}
            apiLatency={apiLatency}
          />
        </div>
      </div>

      {/* Replace Order Dialog */}
      <Dialog open={!!replaceOrderDraft} onOpenChange={(open) => !open && closeReplaceDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Replace order</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="text-muted-foreground">
              Update price/size for {replaceOrderDraft?.symbol} ({replaceOrderDraft?.side})
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">New price</label>
              <Input
                type="number"
                step="any"
                value={replacePrice}
                onChange={(e) => setReplacePrice(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">New size</label>
              <Input
                type="number"
                step="any"
                value={replaceSize}
                onChange={(e) => setReplaceSize(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={closeReplaceDialog}>Cancel</Button>
            <Button onClick={handleReplace} disabled={!!replacingId}>
              {replacingId ? "Replacing..." : "Replace"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Unified Trade Detail Drawer */}
      <TradeInspectorDrawer
        open={!!selectedFill}
        onOpenChange={(open) => !open && setSelectedFill(null)}
        trade={selectedFill ? {
          id: selectedFill.id,
          symbol: selectedFill.symbol,
          side: selectedFill.side,
          timestamp: selectedFill.time,
          quantity: selectedFill.quantity,
          entryPrice: selectedFill.entryPrice,
          exitPrice: selectedFill.exitPrice,
          pnl: selectedFill.pnl,
          fees: selectedFill.fee,
          strategy: selectedFill.strategy,
          latency: selectedFill.latency,
          slippage: selectedFill.slippage,
          decision_id: selectedFill.decisionId,
        } : null}
        onReplay={(trade) => handleOpenReplay({
          symbol: trade.symbol,
          timestamp: trade.timestamp,
          id: trade.id,
        })}
      />
    </TooltipProvider>
  );
}
