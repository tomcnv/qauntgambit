/**
 * ReplayResultsViewer Component
 * 
 * Displays replay validation results including:
 * - Replay match rate as a percentage with visual indicator
 * - Change categories breakdown (expected, unexpected, improved, degraded)
 * - Stage-by-stage diff visualization
 * - Sample changed decisions inspector
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 7.2, 7.3, 7.6**
 */

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { ScrollArea } from "./ui/scroll-area";
import { Separator } from "./ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "./ui/tooltip";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { useQuery } from "@tanstack/react-query";
import { 
  CheckCircle, 
  XCircle, 
  AlertTriangle, 
  Loader2, 
  RefreshCw,
  TrendingUp,
  TrendingDown,
  GitCompare,
  Layers,
  Clock,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  FileSearch,
  BarChart3
} from "lucide-react";
import { cn } from "../lib/utils";
import { useState } from "react";
import { botApiBaseUrl } from "../lib/quantgambit-url";

// ============================================================================
// Types
// ============================================================================

export interface ReplayResult {
  original_decision_id: string;
  original_decision: string;
  replayed_decision: string;
  original_signal?: Record<string, any> | null;
  replayed_signal?: Record<string, any> | null;
  original_rejection_stage?: string | null;
  replayed_rejection_stage?: string | null;
  matches: boolean;
  change_category: "expected" | "unexpected" | "improved" | "degraded";
  stage_diff?: string | null;
  timestamp: string;
  symbol: string;
}

export interface ReplayReport {
  run_id: string;
  run_at: string;
  start_time: string;
  end_time: string;
  total_replayed: number;
  matches: number;
  changes: number;
  match_rate: number;
  changes_by_category: Record<string, number>;
  changes_by_stage: Record<string, number>;
  sample_changes: ReplayResult[];
}

export interface ReplayResultsResponse {
  success: boolean;
  report: ReplayReport;
}

export interface TriggerReplayRequest {
  start_time: string;
  end_time: string;
  symbol?: string;
  decision_filter?: "accepted" | "rejected";
  max_decisions?: number;
}

export interface TriggerReplayResponse {
  success: boolean;
  run_id: string;
  message: string;
}

// ============================================================================
// API Functions
// ============================================================================

function getBotApiBaseUrl(): string {
  return botApiBaseUrl();
}

export const triggerReplayValidation = async (params: TriggerReplayRequest): Promise<TriggerReplayResponse> => {
  const response = await fetch(`${getBotApiBaseUrl()}/replay/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(params),
  });
  
  if (!response.ok) {
    throw new Error(`Failed to trigger replay: ${response.statusText}`);
  }
  
  return response.json();
};

export const fetchReplayResults = async (runId: string): Promise<ReplayResultsResponse> => {
  const response = await fetch(`${getBotApiBaseUrl()}/replay/results/${runId}`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    throw new Error(`Failed to fetch replay results: ${response.statusText}`);
  }
  
  return response.json();
};

// ============================================================================
// Custom Hooks
// ============================================================================

export const useReplayResults = (runId: string | null) =>
  useQuery<ReplayResultsResponse>({
    queryKey: ["replay-results", runId],
    queryFn: () => fetchReplayResults(runId!),
    enabled: !!runId,
    staleTime: 30000, // 30 seconds
    refetchInterval: (data) => {
      // Stop polling once we have results
      return data ? false : 5000;
    },
  });

// ============================================================================
// Helper Functions
// ============================================================================

const formatTimestamp = (timestamp: string): string => {
  const date = new Date(timestamp);
  return date.toLocaleString([], { 
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit', 
    minute: '2-digit',
  });
};

const formatPercent = (value: number): string => {
  return `${(value * 100).toFixed(1)}%`;
};

const getCategoryColor = (category: string): string => {
  switch (category) {
    case "improved":
      return "text-green-500";
    case "degraded":
      return "text-red-500";
    case "expected":
      return "text-blue-500";
    case "unexpected":
      return "text-amber-500";
    default:
      return "text-muted-foreground";
  }
};

const getCategoryBgColor = (category: string): string => {
  switch (category) {
    case "improved":
      return "bg-green-500/10 border-green-500/30";
    case "degraded":
      return "bg-red-500/10 border-red-500/30";
    case "expected":
      return "bg-blue-500/10 border-blue-500/30";
    case "unexpected":
      return "bg-amber-500/10 border-amber-500/30";
    default:
      return "bg-muted";
  }
};

const getCategoryIcon = (category: string) => {
  switch (category) {
    case "improved":
      return <TrendingUp className="h-4 w-4 text-green-500" />;
    case "degraded":
      return <TrendingDown className="h-4 w-4 text-red-500" />;
    case "expected":
      return <CheckCircle className="h-4 w-4 text-blue-500" />;
    case "unexpected":
      return <AlertTriangle className="h-4 w-4 text-amber-500" />;
    default:
      return null;
  }
};

const getCategoryDescription = (category: string): string => {
  switch (category) {
    case "improved":
      return "Previously rejected, now accepted";
    case "degraded":
      return "Previously accepted, now rejected";
    case "expected":
      return "Expected change based on code updates";
    case "unexpected":
      return "Unexpected change requiring investigation";
    default:
      return "Unknown category";
  }
};

const parseStageTransition = (stageDiff: string): { from: string; to: string } | null => {
  if (!stageDiff) return null;
  const match = stageDiff.match(/^(.+)->(.+)$/);
  if (match) {
    return { from: match[1] || "none", to: match[2] || "none" };
  }
  return null;
};

// ============================================================================
// Sub-Components
// ============================================================================

interface MatchRateIndicatorProps {
  matchRate: number;
  totalReplayed: number;
  matches: number;
  changes: number;
}

function MatchRateIndicator({ matchRate, totalReplayed, matches, changes }: MatchRateIndicatorProps) {
  const matchPercent = matchRate * 100;
  const isHighMatch = matchPercent >= 95;
  const isMediumMatch = matchPercent >= 80 && matchPercent < 95;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Match Rate</span>
        <span className={cn(
          "text-2xl font-bold",
          isHighMatch 
            ? "text-green-500"
            : isMediumMatch
            ? "text-amber-500"
            : "text-red-500"
        )}>
          {formatPercent(matchRate)}
        </span>
      </div>
      <Progress 
        value={matchPercent} 
        className={cn(
          "h-3",
          isHighMatch 
            ? "[&>div]:bg-green-500"
            : isMediumMatch
            ? "[&>div]:bg-amber-500"
            : "[&>div]:bg-red-500"
        )}
      />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{matches.toLocaleString()} matches</span>
        <span>{changes.toLocaleString()} changes</span>
      </div>
      <div className="text-xs text-muted-foreground text-center">
        {totalReplayed.toLocaleString()} decisions replayed
      </div>
    </div>
  );
}

interface CategoryBreakdownProps {
  changesByCategory: Record<string, number>;
  totalChanges: number;
}

function CategoryBreakdown({ changesByCategory, totalChanges }: CategoryBreakdownProps) {
  const categories = ["improved", "degraded", "expected", "unexpected"];
  const sortedCategories = categories
    .map(cat => ({ category: cat, count: changesByCategory[cat] || 0 }))
    .filter(item => item.count > 0)
    .sort((a, b) => b.count - a.count);

  if (sortedCategories.length === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-4">
        No changes detected - all decisions match
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {sortedCategories.map(({ category, count }) => {
        const percentage = totalChanges > 0 ? (count / totalChanges) * 100 : 0;
        return (
          <TooltipProvider key={category}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="space-y-1 cursor-help">
                  <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      {getCategoryIcon(category)}
                      <span className={cn("capitalize", getCategoryColor(category))}>
                        {category}
                      </span>
                    </div>
                    <span className="font-medium">{count} ({percentage.toFixed(0)}%)</span>
                  </div>
                  <div className="h-2 bg-muted rounded-full overflow-hidden">
                    <div 
                      className={cn(
                        "h-full rounded-full transition-all",
                        category === "improved" && "bg-green-500",
                        category === "degraded" && "bg-red-500",
                        category === "expected" && "bg-blue-500",
                        category === "unexpected" && "bg-amber-500"
                      )}
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">
                <p className="text-xs">{getCategoryDescription(category)}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        );
      })}
    </div>
  );
}

interface StageBreakdownProps {
  changesByStage: Record<string, number>;
  totalChanges: number;
}

function StageBreakdown({ changesByStage, totalChanges }: StageBreakdownProps) {
  const sortedStages = Object.entries(changesByStage)
    .sort(([, a], [, b]) => b - a);

  if (sortedStages.length === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-4">
        No stage transitions detected
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {sortedStages.map(([stageDiff, count]) => {
        const percentage = totalChanges > 0 ? (count / totalChanges) * 100 : 0;
        const transition = parseStageTransition(stageDiff);
        
        return (
          <div key={stageDiff} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Layers className="h-3 w-3" />
                {transition ? (
                  <span className="flex items-center gap-1 font-mono text-xs">
                    <span className="text-red-400">{transition.from}</span>
                    <ArrowRight className="h-3 w-3" />
                    <span className="text-green-400">{transition.to}</span>
                  </span>
                ) : (
                  <span className="font-mono text-xs">{stageDiff}</span>
                )}
              </div>
              <span className="font-medium">{count} ({percentage.toFixed(0)}%)</span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div 
                className="h-full rounded-full transition-all bg-purple-500"
                style={{ width: `${percentage}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface ChangedDecisionItemProps {
  result: ReplayResult;
  isExpanded: boolean;
  onToggle: () => void;
}

function ChangedDecisionItem({ result, isExpanded, onToggle }: ChangedDecisionItemProps) {
  const transition = result.stage_diff ? parseStageTransition(result.stage_diff) : null;

  return (
    <div className={cn(
      "rounded-lg border p-3",
      getCategoryBgColor(result.change_category)
    )}>
      <div 
        className="flex items-start gap-3 cursor-pointer"
        onClick={onToggle}
      >
        <div className="flex-shrink-0 mt-0.5">
          {getCategoryIcon(result.change_category)}
        </div>
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-sm">{result.symbol.replace('-SWAP', '')}</span>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {formatTimestamp(result.timestamp)}
              </span>
              {isExpanded ? (
                <ChevronDown className="h-3 w-3 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-3 w-3 text-muted-foreground" />
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="outline" className={cn(
              "text-[10px]",
              result.original_decision === "accepted" 
                ? "bg-green-500/10 text-green-600 border-green-500/30"
                : "bg-muted text-muted-foreground"
            )}>
              Original: {result.original_decision}
            </Badge>
            <GitCompare className="h-3 w-3 text-muted-foreground" />
            <Badge variant="outline" className={cn(
              "text-[10px]",
              result.replayed_decision === "accepted" 
                ? "bg-blue-500/10 text-blue-600 border-blue-500/30"
                : "bg-muted text-muted-foreground"
            )}>
              Replayed: {result.replayed_decision}
            </Badge>
          </div>
          {transition && (
            <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">Stage:</span>
              <span className="font-mono text-red-400">{transition.from}</span>
              <ArrowRight className="h-3 w-3" />
              <span className="font-mono text-green-400">{transition.to}</span>
            </div>
          )}
        </div>
      </div>
      
      {isExpanded && (
        <div className="mt-3 pt-3 border-t border-border/50 space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-muted-foreground mb-1">Original Rejection Stage</div>
              <div className="text-sm font-mono bg-background/50 p-2 rounded">
                {result.original_rejection_stage || "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">Replayed Rejection Stage</div>
              <div className="text-sm font-mono bg-background/50 p-2 rounded">
                {result.replayed_rejection_stage || "—"}
              </div>
            </div>
          </div>
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Decision ID:</span>{" "}
            <span className="font-mono">{result.original_decision_id}</span>
          </div>
        </div>
      )}
    </div>
  );
}

interface SampleChangesListProps {
  sampleChanges: ReplayResult[];
}

function SampleChangesList({ sampleChanges }: SampleChangesListProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpanded = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  if (sampleChanges.length === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-8">
        No changed decisions to display
      </div>
    );
  }

  return (
    <ScrollArea className="h-[350px] pr-4">
      <div className="space-y-2">
        {sampleChanges.map((result) => (
          <ChangedDecisionItem
            key={result.original_decision_id}
            result={result}
            isExpanded={expandedIds.has(result.original_decision_id)}
            onToggle={() => toggleExpanded(result.original_decision_id)}
          />
        ))}
      </div>
    </ScrollArea>
  );
}

// ============================================================================
// Main Component
// ============================================================================

interface ReplayResultsViewerProps {
  /** Replay run ID to display results for */
  runId?: string | null;
  /** Pre-loaded report data (optional, will fetch if not provided) */
  report?: ReplayReport | null;
  /** Whether to show in compact mode */
  compact?: boolean;
}

export function ReplayResultsViewer({ 
  runId,
  report: preloadedReport,
  compact = false,
}: ReplayResultsViewerProps) {
  const { 
    data: fetchedData, 
    isLoading, 
    error,
    refetch 
  } = useReplayResults(preloadedReport ? null : runId || null);

  const report = preloadedReport || fetchedData?.report;

  // Loading state
  if (isLoading && !report) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading replay results...</span>
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (error && !report) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <span className="ml-2 text-muted-foreground">Failed to load replay results</span>
        </CardContent>
      </Card>
    );
  }

  // No data state
  if (!report) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <RefreshCw className="h-4 w-4" />
              Replay Validation
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8">
            <FileSearch className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              No replay results available
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Run a replay validation to see results
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const matchPercent = report.match_rate * 100;
  const isHighMatch = matchPercent >= 95;
  const isMediumMatch = matchPercent >= 80 && matchPercent < 95;

  // Compact version for header/sidebar
  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2 cursor-pointer">
              <RefreshCw className="h-4 w-4 text-muted-foreground" />
              <Badge 
                variant="outline" 
                className={cn(
                  isHighMatch 
                    ? "bg-green-500/10 text-green-600 border-green-500/30"
                    : isMediumMatch
                    ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                    : "bg-red-500/10 text-red-600 border-red-500/30"
                )}
              >
                {formatPercent(report.match_rate)} Match
              </Badge>
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs">
            <div className="space-y-2">
              <p className="font-medium">Replay Validation Results</p>
              <div className="text-xs space-y-1">
                <div className="flex justify-between gap-4">
                  <span>Total Replayed:</span>
                  <span className="font-medium">{report.total_replayed.toLocaleString()}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span>Matches:</span>
                  <span className="font-medium text-green-500">{report.matches.toLocaleString()}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span>Changes:</span>
                  <span className="font-medium text-amber-500">{report.changes.toLocaleString()}</span>
                </div>
              </div>
            </div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // Full card version
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            Replay Validation Results
          </CardTitle>
          <Badge 
            variant="outline" 
            className={cn(
              isHighMatch 
                ? "bg-green-500/10 text-green-600 border-green-500/30"
                : isMediumMatch
                ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                : "bg-red-500/10 text-red-600 border-red-500/30"
            )}
          >
            <BarChart3 className="h-3 w-3 mr-1" />
            {report.total_replayed.toLocaleString()} decisions
          </Badge>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            <span>Run: {formatTimestamp(report.run_at)}</span>
          </div>
          <span>•</span>
          <span>
            Range: {formatTimestamp(report.start_time)} - {formatTimestamp(report.end_time)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Match Rate Section */}
        <MatchRateIndicator
          matchRate={report.match_rate}
          totalReplayed={report.total_replayed}
          matches={report.matches}
          changes={report.changes}
        />

        {/* Stats Grid */}
        <div className="grid grid-cols-4 gap-3">
          <div className="space-y-1 p-3 rounded-lg bg-green-500/5 border border-green-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <TrendingUp className="h-3 w-3 text-green-500" />
              Improved
            </div>
            <p className="text-lg font-semibold text-green-500">
              {(report.changes_by_category["improved"] || 0).toLocaleString()}
            </p>
          </div>
          <div className="space-y-1 p-3 rounded-lg bg-red-500/5 border border-red-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <TrendingDown className="h-3 w-3 text-red-500" />
              Degraded
            </div>
            <p className="text-lg font-semibold text-red-500">
              {(report.changes_by_category["degraded"] || 0).toLocaleString()}
            </p>
          </div>
          <div className="space-y-1 p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <CheckCircle className="h-3 w-3 text-blue-500" />
              Expected
            </div>
            <p className="text-lg font-semibold text-blue-500">
              {(report.changes_by_category["expected"] || 0).toLocaleString()}
            </p>
          </div>
          <div className="space-y-1 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <AlertTriangle className="h-3 w-3 text-amber-500" />
              Unexpected
            </div>
            <p className="text-lg font-semibold text-amber-500">
              {(report.changes_by_category["unexpected"] || 0).toLocaleString()}
            </p>
          </div>
        </div>

        <Separator />

        {/* Change Categories Breakdown */}
        <Collapsible defaultOpen={report.changes > 0}>
          <CollapsibleTrigger className="flex items-center justify-between w-full py-2 hover:bg-muted/50 rounded px-2 -mx-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <BarChart3 className="h-4 w-4" />
              Change Categories
            </div>
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-3">
            <CategoryBreakdown 
              changesByCategory={report.changes_by_category}
              totalChanges={report.changes}
            />
          </CollapsibleContent>
        </Collapsible>

        <Separator />

        {/* Stage-by-Stage Diff Visualization */}
        <Collapsible defaultOpen={Object.keys(report.changes_by_stage).length > 0}>
          <CollapsibleTrigger className="flex items-center justify-between w-full py-2 hover:bg-muted/50 rounded px-2 -mx-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Layers className="h-4 w-4" />
              Stage Transitions
              {Object.keys(report.changes_by_stage).length > 0 && (
                <Badge variant="outline" className="text-[10px] ml-2">
                  {Object.keys(report.changes_by_stage).length} stages
                </Badge>
              )}
            </div>
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-3">
            <StageBreakdown 
              changesByStage={report.changes_by_stage}
              totalChanges={report.changes}
            />
          </CollapsibleContent>
        </Collapsible>

        <Separator />

        {/* Sample Changed Decisions Inspector */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <FileSearch className="h-4 w-4" />
              Sample Changed Decisions
            </div>
            {report.sample_changes.length > 0 && (
              <Badge variant="outline" className="text-[10px]">
                {report.sample_changes.length} samples
              </Badge>
            )}
          </div>
          <SampleChangesList sampleChanges={report.sample_changes} />
        </div>

        {/* Warning for high change rate */}
        {report.match_rate < 0.80 && report.total_replayed >= 100 && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-amber-600">High Change Rate Detected</p>
              <p className="text-xs text-muted-foreground mt-1">
                Match rate is below 80% over {report.total_replayed.toLocaleString()} decisions. 
                Review the changes to ensure pipeline behavior is as expected.
              </p>
            </div>
          </div>
        )}

        {/* Warning for degraded decisions */}
        {(report.changes_by_category["degraded"] || 0) > 0 && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <XCircle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-red-600">Degraded Decisions Detected</p>
              <p className="text-xs text-muted-foreground mt-1">
                {report.changes_by_category["degraded"]} decision(s) that were previously accepted 
                are now being rejected. This may indicate a regression.
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ReplayResultsViewer;
