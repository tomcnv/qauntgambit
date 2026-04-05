/**
 * Metrics Comparison Page
 * 
 * Displays the MetricsComparisonChart component for comparing
 * live trading metrics against backtest results.
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 9.3, 9.4, 9.6**
 */

import { useState } from "react";
import { DashBar } from "../../components/DashBar";
import { MetricsComparisonChart } from "../../components/MetricsComparisonChart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Label } from "../../components/ui/label";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  ArrowLeft,
  Info,
  TrendingUp,
  Scale,
  Activity,
  Loader2,
  RefreshCw,
  GitCompare,
} from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { botApiBaseUrl } from "../../lib/quantgambit-url";

// Dynamic URL detection for remote access
function getBotApiBaseUrl(): string {
  return botApiBaseUrl();
}

const fetchBacktestRuns = async () => {
  const response = await fetch(`${getBotApiBaseUrl()}/research/backtests?status=completed&limit=20`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    return { backtests: [] };
  }
  return response.json();
};

export default function MetricsComparisonPage() {
  const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(null);
  const [livePeriodHours, setLivePeriodHours] = useState<number>(24);

  const { data: backtestsData, isLoading: backtestsLoading } = useQuery({
    queryKey: ["backtests-for-metrics"],
    queryFn: fetchBacktestRuns,
    staleTime: 30000,
  });

  const backtests = backtestsData?.backtests || [];

  return (
    <TooltipProvider>
      <div className="flex flex-col min-h-screen bg-background">
        <DashBar />
        
        <main className="flex-1 p-6">
          <div className="max-w-6xl mx-auto space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <Link to="/backtesting">
                  <Button variant="ghost" size="sm">
                    <ArrowLeft className="h-4 w-4 mr-1" />
                    Backtesting
                  </Button>
                </Link>
                <Separator orientation="vertical" className="h-6" />
                <div>
                  <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                    <BarChart3 className="h-6 w-6" />
                    Metrics Comparison
                  </h1>
                  <p className="text-sm text-muted-foreground mt-1">
                    Compare live trading metrics against backtest results
                  </p>
                </div>
              </div>
            </div>

            {/* Info Banner */}
            <Card className="border-blue-500/30 bg-blue-500/5">
              <CardContent className="py-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-blue-600">Unified Metrics</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      This comparison uses identical calculation methodologies for both live and backtest
                      metrics, ensuring accurate side-by-side comparison. Significant differences ({">"} 10%)
                      are highlighted with potential explanations through divergence attribution analysis.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Comparison Controls */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium flex items-center gap-2">
                  <GitCompare className="h-4 w-4" />
                  Comparison Settings
                </CardTitle>
                <CardDescription>
                  Select a backtest run and live period to compare
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <Label>Backtest Run</Label>
                    {backtestsLoading ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading backtests...
                      </div>
                    ) : backtests.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No completed backtests available
                      </p>
                    ) : (
                      <Select
                        value={selectedBacktestId || ""}
                        onValueChange={(value) => setSelectedBacktestId(value || null)}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select a backtest run..." />
                        </SelectTrigger>
                        <SelectContent>
                          {backtests.map((bt: any) => (
                            <SelectItem key={bt.run_id || bt.id} value={bt.run_id || bt.id}>
                              <div className="flex flex-col">
                                <span>{bt.name || `Backtest ${(bt.run_id || bt.id)?.slice(0, 8)}`}</span>
                                <span className="text-xs text-muted-foreground">
                                  {new Date(bt.created_at).toLocaleDateString()} • {bt.symbol}
                                </span>
                              </div>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label>Live Period</Label>
                    <Select
                      value={livePeriodHours.toString()}
                      onValueChange={(value) => setLivePeriodHours(parseInt(value))}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1">Last 1 hour</SelectItem>
                        <SelectItem value="6">Last 6 hours</SelectItem>
                        <SelectItem value="12">Last 12 hours</SelectItem>
                        <SelectItem value="24">Last 24 hours</SelectItem>
                        <SelectItem value="48">Last 48 hours</SelectItem>
                        <SelectItem value="168">Last 7 days</SelectItem>
                        <SelectItem value="720">Last 30 days</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Main Metrics Comparison Chart */}
            <MetricsComparisonChart
              backtestRunId={selectedBacktestId}
              livePeriodHours={livePeriodHours}
            />

            {/* Metric Categories Overview */}
            <div className="grid grid-cols-4 gap-4">
              <Card>
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-green-500/10">
                      <TrendingUp className="h-5 w-5 text-green-500" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Return Metrics</p>
                      <p className="text-xs text-muted-foreground">Total & annualized returns</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-blue-500/10">
                      <Scale className="h-5 w-5 text-blue-500" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Risk Metrics</p>
                      <p className="text-xs text-muted-foreground">Sharpe, Sortino, drawdown</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-purple-500/10">
                      <Activity className="h-5 w-5 text-purple-500" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Trade Metrics</p>
                      <p className="text-xs text-muted-foreground">Win rate, profit factor</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="py-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-amber-500/10">
                      <RefreshCw className="h-5 w-5 text-amber-500" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">Execution Metrics</p>
                      <p className="text-xs text-muted-foreground">Slippage, latency, fills</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Related Links */}
            <div className="grid grid-cols-3 gap-4">
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/backtesting">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <BarChart3 className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Backtesting</p>
                        <p className="text-xs text-muted-foreground">Run and manage backtests</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
              
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/replay-validation">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <RefreshCw className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Replay Validation</p>
                        <p className="text-xs text-muted-foreground">Validate decision changes</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
              
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/config-management">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <GitCompare className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Config Management</p>
                        <p className="text-xs text-muted-foreground">Compare configurations</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
            </div>
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
