/**
 * ConfigVersionManager Component
 * 
 * Displays configuration version management UI including:
 * - Current live config version with timestamp
 * - Config diff viewer for backtest vs live (critical/warning/info categorization)
 * - Config history timeline
 * - Visual indicators for diff severity
 * 
 * Feature: trading-pipeline-integration
 * **Validates: Requirements 1.4, 1.6**
 */

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { ScrollArea } from "./ui/scroll-area";
import { Separator } from "./ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "./ui/tooltip";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";
import { useQuery } from "@tanstack/react-query";
import { 
  Settings, 
  AlertTriangle, 
  AlertCircle, 
  Info, 
  Loader2, 
  Clock,
  ChevronDown,
  ChevronRight,
  GitCompare,
  History,
  CheckCircle,
  XCircle
} from "lucide-react";
import { cn } from "../lib/utils";
import { useState } from "react";
import { botApiBaseUrl } from "../lib/quantgambit-url";

// ============================================================================
// Types
// ============================================================================

export interface ConfigDiffItem {
  key: string;
  old: any;
  new: any;
}

export interface ConfigDiffResponse {
  source_version: string;
  target_version: string;
  critical_diffs: ConfigDiffItem[];
  warning_diffs: ConfigDiffItem[];
  info_diffs: ConfigDiffItem[];
  has_critical_diffs: boolean;
  total_diffs: number;
}

export interface ConfigVersion {
  version_id: string;
  created_at: string;
  created_by: string;
  config_hash: string;
  parameters: Record<string, any>;
}

export interface ConfigVersionHistoryItem {
  version_id: string;
  created_at: string;
  created_by: string;
  config_hash: string;
  change_summary?: string;
}

// ============================================================================
// API Functions
// ============================================================================

function getBotApiBaseUrl(): string {
  return botApiBaseUrl();
}

export const fetchBacktestConfigDiff = async (runId: string): Promise<ConfigDiffResponse> => {
  const response = await fetch(`${getBotApiBaseUrl()}/research/backtests/${runId}/config-diff`, {
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    throw new Error(`Failed to fetch config diff: ${response.statusText}`);
  }
  
  return response.json();
};

// ============================================================================
// Custom Hooks
// ============================================================================

export const useBacktestConfigDiff = (runId: string | null) =>
  useQuery<ConfigDiffResponse>({
    queryKey: ["backtest-config-diff", runId],
    queryFn: () => fetchBacktestConfigDiff(runId!),
    enabled: !!runId,
    staleTime: 30000, // 30 seconds
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

const formatValue = (value: any): string => {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  if (typeof value === "number") {
    return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  return String(value);
};

const getSeverityColor = (severity: "critical" | "warning" | "info"): string => {
  switch (severity) {
    case "critical":
      return "text-red-500";
    case "warning":
      return "text-amber-500";
    case "info":
      return "text-blue-500";
    default:
      return "text-muted-foreground";
  }
};

const getSeverityBgColor = (severity: "critical" | "warning" | "info"): string => {
  switch (severity) {
    case "critical":
      return "bg-red-500/10 border-red-500/30";
    case "warning":
      return "bg-amber-500/10 border-amber-500/30";
    case "info":
      return "bg-blue-500/10 border-blue-500/30";
    default:
      return "bg-muted";
  }
};

const getSeverityIcon = (severity: "critical" | "warning" | "info") => {
  switch (severity) {
    case "critical":
      return <AlertCircle className="h-4 w-4 text-red-500" />;
    case "warning":
      return <AlertTriangle className="h-4 w-4 text-amber-500" />;
    case "info":
      return <Info className="h-4 w-4 text-blue-500" />;
    default:
      return null;
  }
};

// ============================================================================
// Sub-Components
// ============================================================================

interface DiffItemProps {
  item: ConfigDiffItem;
  severity: "critical" | "warning" | "info";
}

function DiffItem({ item, severity }: DiffItemProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isComplex = typeof item.old === "object" || typeof item.new === "object";

  return (
    <div className={cn(
      "rounded-lg border p-3",
      getSeverityBgColor(severity)
    )}>
      <div 
        className={cn(
          "flex items-start gap-3",
          isComplex && "cursor-pointer"
        )}
        onClick={() => isComplex && setIsExpanded(!isExpanded)}
      >
        <div className="flex-shrink-0 mt-0.5">
          {getSeverityIcon(severity)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-sm font-mono">{item.key}</span>
            {isComplex && (
              <span className="text-xs text-muted-foreground">
                {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </span>
            )}
          </div>
          {!isComplex && (
            <div className="flex items-center gap-2 mt-1 text-xs">
              <span className="text-red-400 line-through">{formatValue(item.old)}</span>
              <span className="text-muted-foreground">→</span>
              <span className="text-green-400">{formatValue(item.new)}</span>
            </div>
          )}
        </div>
      </div>
      {isComplex && isExpanded && (
        <div className="mt-3 pt-3 border-t border-border/50">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-muted-foreground mb-1">Live (Old)</div>
              <pre className="text-xs bg-background/50 p-2 rounded overflow-auto max-h-32">
                {formatValue(item.old)}
              </pre>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">Backtest (New)</div>
              <pre className="text-xs bg-background/50 p-2 rounded overflow-auto max-h-32">
                {formatValue(item.new)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface DiffSectionProps {
  title: string;
  items: ConfigDiffItem[];
  severity: "critical" | "warning" | "info";
  defaultOpen?: boolean;
}

function DiffSection({ title, items, severity, defaultOpen = false }: DiffSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  if (items.length === 0) {
    return null;
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex items-center justify-between w-full py-2 hover:bg-muted/50 rounded px-2 -mx-2">
        <div className="flex items-center gap-2">
          {getSeverityIcon(severity)}
          <span className="font-medium text-sm">{title}</span>
          <Badge 
            variant="outline" 
            className={cn("text-[10px]", getSeverityBgColor(severity))}
          >
            {items.length}
          </Badge>
        </div>
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 pt-2">
        {items.map((item, index) => (
          <DiffItem key={`${item.key}-${index}`} item={item} severity={severity} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

interface ConfigVersionBadgeProps {
  version: string;
  createdBy?: string;
  timestamp?: string;
}

function ConfigVersionBadge({ version, createdBy, timestamp }: ConfigVersionBadgeProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className="font-mono text-xs">
            {version.length > 12 ? `${version.slice(0, 12)}...` : version}
          </Badge>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <div className="space-y-1 text-xs">
            <div><span className="text-muted-foreground">Version:</span> {version}</div>
            {createdBy && <div><span className="text-muted-foreground">Created by:</span> {createdBy}</div>}
            {timestamp && <div><span className="text-muted-foreground">Time:</span> {formatTimestamp(timestamp)}</div>}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

interface HistoryTimelineItemProps {
  item: ConfigVersionHistoryItem;
  isLatest?: boolean;
}

function HistoryTimelineItem({ item, isLatest = false }: HistoryTimelineItemProps) {
  return (
    <div className="flex items-start gap-3 relative">
      <div className={cn(
        "flex-shrink-0 w-2 h-2 rounded-full mt-2",
        isLatest ? "bg-green-500" : "bg-muted-foreground/50"
      )} />
      <div className="flex-1 min-w-0 pb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-foreground">
            {item.version_id.length > 16 ? `${item.version_id.slice(0, 16)}...` : item.version_id}
          </span>
          {isLatest && (
            <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600 border-green-500/30">
              Live
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          <span>{formatTimestamp(item.created_at)}</span>
          <span>•</span>
          <span>{item.created_by}</span>
        </div>
        {item.change_summary && (
          <p className="text-xs text-muted-foreground mt-1">{item.change_summary}</p>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

interface ConfigVersionManagerProps {
  /** Backtest run ID to compare against live config */
  backtestRunId?: string | null;
  /** Current live config version info */
  liveConfig?: ConfigVersion | null;
  /** Config version history */
  configHistory?: ConfigVersionHistoryItem[];
  /** Whether to show in compact mode */
  compact?: boolean;
}

export function ConfigVersionManager({ 
  backtestRunId,
  liveConfig,
  configHistory = [],
  compact = false,
}: ConfigVersionManagerProps) {
  const { 
    data: configDiff, 
    isLoading: diffLoading, 
    error: diffError 
  } = useBacktestConfigDiff(backtestRunId || null);

  // Loading state
  if (diffLoading && backtestRunId) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading configuration diff...</span>
        </CardContent>
      </Card>
    );
  }

  // Compact version for header/sidebar
  if (compact) {
    const hasCritical = configDiff?.has_critical_diffs || false;
    const totalDiffs = configDiff?.total_diffs || 0;

    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2 cursor-pointer">
              <Settings className="h-4 w-4 text-muted-foreground" />
              {totalDiffs > 0 ? (
                <Badge 
                  variant="outline" 
                  className={cn(
                    hasCritical 
                      ? "bg-red-500/10 text-red-600 border-red-500/30"
                      : "bg-amber-500/10 text-amber-600 border-amber-500/30"
                  )}
                >
                  {totalDiffs} diff{totalDiffs !== 1 ? 's' : ''}
                </Badge>
              ) : (
                <Badge variant="outline" className="bg-green-500/10 text-green-600 border-green-500/30">
                  <CheckCircle className="h-3 w-3 mr-1" />
                  Synced
                </Badge>
              )}
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-xs">
            <div className="space-y-2">
              <p className="font-medium">Configuration Status</p>
              {configDiff ? (
                <div className="text-xs space-y-1">
                  <div className="flex justify-between gap-4">
                    <span>Critical:</span>
                    <span className={cn("font-medium", configDiff.critical_diffs.length > 0 && "text-red-500")}>
                      {configDiff.critical_diffs.length}
                    </span>
                  </div>
                  <div className="flex justify-between gap-4">
                    <span>Warnings:</span>
                    <span className={cn("font-medium", configDiff.warning_diffs.length > 0 && "text-amber-500")}>
                      {configDiff.warning_diffs.length}
                    </span>
                  </div>
                  <div className="flex justify-between gap-4">
                    <span>Info:</span>
                    <span className="font-medium text-blue-500">{configDiff.info_diffs.length}</span>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No backtest selected for comparison</p>
              )}
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
            <Settings className="h-4 w-4" />
            Configuration Version Manager
          </CardTitle>
          {liveConfig && (
            <ConfigVersionBadge 
              version={liveConfig.version_id}
              createdBy={liveConfig.created_by}
              timestamp={liveConfig.created_at}
            />
          )}
        </div>
        {liveConfig && (
          <p className="text-xs text-muted-foreground">
            Live config: {liveConfig.version_id.slice(0, 16)}... • Updated {formatTimestamp(liveConfig.created_at)}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Current Live Config Section */}
        {liveConfig && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <CheckCircle className="h-4 w-4 text-green-500" />
              Current Live Configuration
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1 p-3 rounded-lg bg-muted/50">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  Last Updated
                </div>
                <p className="text-sm font-medium">{formatTimestamp(liveConfig.created_at)}</p>
              </div>
              <div className="space-y-1 p-3 rounded-lg bg-muted/50">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Settings className="h-3 w-3" />
                  Config Hash
                </div>
                <p className="text-sm font-medium font-mono">
                  {liveConfig.config_hash.slice(0, 12)}...
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Config Diff Section */}
        {backtestRunId && (
          <>
            <Separator />
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <GitCompare className="h-4 w-4" />
                  Config Diff (Live vs Backtest)
                </div>
                {configDiff && (
                  <Badge 
                    variant="outline"
                    className={cn(
                      configDiff.has_critical_diffs
                        ? "bg-red-500/10 text-red-600 border-red-500/30"
                        : configDiff.total_diffs > 0
                        ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
                        : "bg-green-500/10 text-green-600 border-green-500/30"
                    )}
                  >
                    {configDiff.total_diffs} difference{configDiff.total_diffs !== 1 ? 's' : ''}
                  </Badge>
                )}
              </div>

              {diffError ? (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                  <XCircle className="h-4 w-4 text-red-500" />
                  <span className="text-sm text-red-600">Failed to load config diff</span>
                </div>
              ) : configDiff ? (
                <div className="space-y-4">
                  {/* Version comparison header */}
                  <div className="flex items-center justify-between text-xs text-muted-foreground p-2 bg-muted/30 rounded">
                    <span>Live: <span className="font-mono">{configDiff.source_version.slice(0, 12)}...</span></span>
                    <span>→</span>
                    <span>Backtest: <span className="font-mono">{configDiff.target_version.slice(0, 12)}...</span></span>
                  </div>

                  {/* No differences */}
                  {configDiff.total_diffs === 0 && (
                    <div className="flex items-center gap-2 p-4 rounded-lg bg-green-500/10 border border-green-500/30">
                      <CheckCircle className="h-5 w-5 text-green-500" />
                      <div>
                        <p className="font-medium text-green-600">Configurations Match</p>
                        <p className="text-xs text-muted-foreground">
                          Live and backtest configurations are identical
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Critical differences warning */}
                  {configDiff.has_critical_diffs && (
                    <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                      <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
                      <div className="text-sm">
                        <p className="font-medium text-red-600">Critical Differences Detected</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {configDiff.critical_diffs.length} critical parameter{configDiff.critical_diffs.length !== 1 ? 's differ' : ' differs'} between live and backtest. 
                          These may significantly impact trading behavior.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Diff sections */}
                  <ScrollArea className="max-h-[400px]">
                    <div className="space-y-4 pr-4">
                      <DiffSection 
                        title="Critical Differences" 
                        items={configDiff.critical_diffs} 
                        severity="critical"
                        defaultOpen={true}
                      />
                      <DiffSection 
                        title="Warning Differences" 
                        items={configDiff.warning_diffs} 
                        severity="warning"
                        defaultOpen={configDiff.critical_diffs.length === 0}
                      />
                      <DiffSection 
                        title="Info Differences" 
                        items={configDiff.info_diffs} 
                        severity="info"
                      />
                    </div>
                  </ScrollArea>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground text-center py-4">
                  Select a backtest to compare configurations
                </div>
              )}
            </div>
          </>
        )}

        {/* Config History Timeline */}
        {configHistory.length > 0 && (
          <>
            <Separator />
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <History className="h-4 w-4" />
                Configuration History
              </div>
              <ScrollArea className="h-[200px] pr-4">
                <div className="relative">
                  {/* Timeline line */}
                  <div className="absolute left-[3px] top-2 bottom-0 w-px bg-border" />
                  
                  {/* Timeline items */}
                  <div className="space-y-0">
                    {configHistory.map((item, index) => (
                      <HistoryTimelineItem 
                        key={item.version_id} 
                        item={item}
                        isLatest={index === 0}
                      />
                    ))}
                  </div>
                </div>
              </ScrollArea>
            </div>
          </>
        )}

        {/* Empty state */}
        {!liveConfig && !backtestRunId && configHistory.length === 0 && (
          <div className="text-center py-8">
            <Settings className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              No configuration data available
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Select a backtest to view configuration differences
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default ConfigVersionManager;
