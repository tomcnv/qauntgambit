/**
 * Replay Validation Page
 * 
 * Displays the ReplayResultsViewer component for viewing
 * replay validation results and decision comparisons.
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 7.2, 7.3, 7.6**
 */

import { useState } from "react";
import { DashBar } from "../../components/DashBar";
import { ReplayResultsViewer, triggerReplayValidation } from "../../components/ReplayResultsViewer";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  ArrowLeft,
  Info,
  Play,
  Calendar,
  Filter,
  Loader2,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import toast from "react-hot-toast";
import { botApiBaseUrl } from "../../lib/quantgambit-url";

const fetchReplayRuns = async () => {
  const response = await fetch(`${botApiBaseUrl()}/replay/runs?limit=20`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    return { runs: [] };
  }
  return response.json();
};

export default function ReplayValidationPage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  
  // Form state for triggering new replay
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [symbol, setSymbol] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<string>("");

  const { data: replayRuns, isLoading: runsLoading, refetch: refetchRuns } = useQuery({
    queryKey: ["replay-runs"],
    queryFn: fetchReplayRuns,
    staleTime: 30000,
  });

  const runs = replayRuns?.runs || [];

  const handleTriggerReplay = async () => {
    if (!startTime || !endTime) {
      toast.error("Please specify start and end times");
      return;
    }

    setIsTriggering(true);
    try {
      const result = await triggerReplayValidation({
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
        symbol: symbol || undefined,
        decision_filter: decisionFilter as "accepted" | "rejected" | undefined,
        max_decisions: 10000,
      });
      
      toast.success(`Replay started: ${result.run_id}`);
      setSelectedRunId(result.run_id);
      refetchRuns();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to trigger replay");
    } finally {
      setIsTriggering(false);
    }
  };

  // Set default time range (last 24 hours)
  const setDefaultTimeRange = () => {
    const now = new Date();
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    setEndTime(now.toISOString().slice(0, 16));
    setStartTime(yesterday.toISOString().slice(0, 16));
  };

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
                    <RefreshCw className="h-6 w-6" />
                    Replay Validation
                  </h1>
                  <p className="text-sm text-muted-foreground mt-1">
                    Replay historical decisions through the current pipeline to validate changes
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
                    <p className="text-sm font-medium text-blue-600">About Replay Validation</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Replay validation re-runs historical trading decisions through the current pipeline
                      to detect behavioral changes. This helps validate code changes don't alter expected
                      behavior and identifies improvements or regressions in decision-making.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Trigger New Replay */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium flex items-center gap-2">
                  <Play className="h-4 w-4" />
                  Run New Replay Validation
                </CardTitle>
                <CardDescription>
                  Specify a time range to replay historical decisions
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-4 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="start-time">Start Time</Label>
                    <Input
                      id="start-time"
                      type="datetime-local"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="end-time">End Time</Label>
                    <Input
                      id="end-time"
                      type="datetime-local"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="symbol">Symbol (Optional)</Label>
                    <Input
                      id="symbol"
                      placeholder="e.g., BTCUSDT"
                      value={symbol}
                      onChange={(e) => setSymbol(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="filter">Decision Filter</Label>
                    <Select value={decisionFilter} onValueChange={setDecisionFilter}>
                      <SelectTrigger id="filter">
                        <SelectValue placeholder="All decisions" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="">All decisions</SelectItem>
                        <SelectItem value="accepted">Accepted only</SelectItem>
                        <SelectItem value="rejected">Rejected only</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-4">
                  <Button onClick={handleTriggerReplay} disabled={isTriggering}>
                    {isTriggering ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        Starting...
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4 mr-1" />
                        Run Replay
                      </>
                    )}
                  </Button>
                  <Button variant="outline" onClick={setDefaultTimeRange}>
                    <Calendar className="h-4 w-4 mr-1" />
                    Last 24 Hours
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Previous Replay Runs */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium flex items-center gap-2">
                  <Filter className="h-4 w-4" />
                  Previous Replay Runs
                </CardTitle>
                <CardDescription>
                  Select a previous replay run to view results
                </CardDescription>
              </CardHeader>
              <CardContent>
                {runsLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading replay runs...
                  </div>
                ) : runs.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No replay runs found. Run a new replay validation above.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {runs.map((run: any) => (
                      <div
                        key={run.run_id}
                        className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-colors ${
                          selectedRunId === run.run_id
                            ? "border-primary bg-primary/5"
                            : "hover:bg-muted/50"
                        }`}
                        onClick={() => setSelectedRunId(run.run_id)}
                      >
                        <div className="flex items-center gap-3">
                          {run.match_rate >= 0.95 ? (
                            <CheckCircle className="h-4 w-4 text-green-500" />
                          ) : run.match_rate >= 0.80 ? (
                            <AlertTriangle className="h-4 w-4 text-amber-500" />
                          ) : (
                            <AlertTriangle className="h-4 w-4 text-red-500" />
                          )}
                          <div>
                            <p className="text-sm font-medium">
                              {run.run_id.slice(0, 12)}...
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {new Date(run.run_at).toLocaleString()}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4">
                          <Badge variant="outline">
                            {run.total_replayed?.toLocaleString() || 0} decisions
                          </Badge>
                          <Badge
                            variant="outline"
                            className={
                              run.match_rate >= 0.95
                                ? "bg-green-500/10 text-green-600 border-green-500/30"
                                : run.match_rate >= 0.80
                                ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                                : "bg-red-500/10 text-red-600 border-red-500/30"
                            }
                          >
                            {((run.match_rate || 0) * 100).toFixed(1)}% match
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Main Replay Results Viewer */}
            <ReplayResultsViewer runId={selectedRunId} />
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
