/**
 * Config Management Page
 * 
 * Displays the ConfigVersionManager component for managing
 * configuration versions and viewing diffs between live and backtest.
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 1.4, 1.6**
 */

import { useState } from "react";
import { DashBar } from "../../components/DashBar";
import { ConfigVersionManager } from "../../components/ConfigVersionManager";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Settings,
  ArrowLeft,
  Info,
  History,
  GitCompare,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { botApiBaseUrl } from "../../lib/quantgambit-url";

// Dynamic URL detection for remote access
function getBotApiBaseUrl(): string {
  return botApiBaseUrl();
}

const fetchLiveConfig = async () => {
  const response = await fetch(`${getBotApiBaseUrl()}/config/live`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    // Return mock data if API not available
    return {
      version_id: "live_config_v1",
      created_at: new Date().toISOString(),
      created_by: "system",
      config_hash: "abc123def456",
      parameters: {},
    };
  }
  return response.json();
};

const fetchConfigHistory = async () => {
  const response = await fetch(`${getBotApiBaseUrl()}/config/history?limit=10`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    // Return mock data if API not available
    return { versions: [] };
  }
  return response.json();
};

const fetchBacktestRuns = async () => {
  const response = await fetch(`${API_BASE_URL}/research/backtests?status=completed&limit=20`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    return { backtests: [] };
  }
  return response.json();
};

export default function ConfigManagementPage() {
  const [selectedBacktestId, setSelectedBacktestId] = useState<string | null>(null);

  const { data: liveConfig, isLoading: configLoading } = useQuery({
    queryKey: ["live-config"],
    queryFn: fetchLiveConfig,
    staleTime: 30000,
  });

  const { data: configHistory } = useQuery({
    queryKey: ["config-history"],
    queryFn: fetchConfigHistory,
    staleTime: 30000,
  });

  const { data: backtestsData, isLoading: backtestsLoading } = useQuery({
    queryKey: ["backtests-for-config"],
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
                <Link to="/settings">
                  <Button variant="ghost" size="sm">
                    <ArrowLeft className="h-4 w-4 mr-1" />
                    Settings
                  </Button>
                </Link>
                <Separator orientation="vertical" className="h-6" />
                <div>
                  <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                    <Settings className="h-6 w-6" />
                    Configuration Management
                  </h1>
                  <p className="text-sm text-muted-foreground mt-1">
                    Manage configuration versions and compare live vs backtest settings
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="outline" size="sm" asChild>
                      <Link to="/audit">
                        <History className="h-4 w-4 mr-1" />
                        Audit Log
                      </Link>
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    View complete configuration change history
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>

            {/* Info Banner */}
            <Card className="border-blue-500/30 bg-blue-500/5">
              <CardContent className="py-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-blue-600">Configuration Parity</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Configuration parity ensures that backtest and live systems use identical settings.
                      Select a backtest run below to compare its configuration against the current live
                      configuration. Critical differences are highlighted and may require acknowledgment
                      before proceeding with backtests.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Backtest Selector */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium flex items-center gap-2">
                  <GitCompare className="h-4 w-4" />
                  Compare Configuration
                </CardTitle>
                <CardDescription>
                  Select a backtest run to compare its configuration against live
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <div className="flex-1 max-w-md">
                    {backtestsLoading ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading backtests...
                      </div>
                    ) : backtests.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No completed backtests available for comparison
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
                                  {new Date(bt.created_at).toLocaleDateString()}
                                </span>
                              </div>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                  {selectedBacktestId && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedBacktestId(null)}
                    >
                      Clear Selection
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Main Config Version Manager */}
            <ConfigVersionManager
              backtestRunId={selectedBacktestId}
              liveConfig={liveConfig}
              configHistory={configHistory?.versions || []}
            />

            {/* Related Links */}
            <div className="grid grid-cols-3 gap-4">
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/settings/trading">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <Settings className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Trading Settings</p>
                        <p className="text-xs text-muted-foreground">Configure trading parameters</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
              
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/backtesting">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <RefreshCw className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Backtesting</p>
                        <p className="text-xs text-muted-foreground">Run and manage backtests</p>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
              
              <Card className="hover:border-primary/50 transition-colors">
                <Link to="/shadow-comparison">
                  <CardContent className="py-4">
                    <div className="flex items-center gap-3">
                      <GitCompare className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">Shadow Comparison</p>
                        <p className="text-xs text-muted-foreground">Compare live vs shadow decisions</p>
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
