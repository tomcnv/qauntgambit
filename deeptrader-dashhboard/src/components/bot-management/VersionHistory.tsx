/**
 * Version History Component
 * Shows config version history with full JSON view and diff comparison
 */

import { useState, useMemo } from "react";
import {
  History,
  ChevronRight,
  RotateCcw,
  Check,
  Clock,
  Zap,
  Code,
  ArrowLeftRight,
  Copy,
  ChevronDown,
  ChevronUp,
  FileJson,
  X,
} from "lucide-react";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useBotExchangeConfigVersions, useCompareBotExchangeConfigVersions } from "../../lib/api/hooks";
import { cn } from "../../lib/utils";
import toast from "react-hot-toast";

interface ConfigVersion {
  id: string;
  version_number: number;
  trading_capital_usd?: number;
  enabled_symbols?: string[];
  risk_config?: Record<string, unknown>;
  execution_config?: Record<string, unknown>;
  profile_overrides?: Record<string, unknown>;
  change_type?: string;
  change_summary?: string;
  was_activated?: boolean;
  activated_at?: string;
  created_at: string;
  created_by?: string;
}

interface VersionHistoryProps {
  configId: string;
  botId?: string;
  currentVersion?: number;
  onRollback?: (version: ConfigVersion) => void;
}

export function VersionHistory({
  configId,
  botId,
  currentVersion,
  onRollback,
}: VersionHistoryProps) {
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareVersionA, setCompareVersionA] = useState<number | null>(null);
  const [compareVersionB, setCompareVersionB] = useState<number | null>(null);

  // NOTE: Hook expects (botId, configId) order
  const { data, isLoading, isError } = useBotExchangeConfigVersions(botId || "", configId);
  const versions = (data?.versions || []) as unknown as ConfigVersion[];

  const selectedVersion = useMemo(
    () => versions.find((v) => v.id === selectedVersionId),
    [versions, selectedVersionId]
  );

  // Auto-select first version when data loads
  useMemo(() => {
    if (versions.length > 0 && !selectedVersionId) {
      setSelectedVersionId(versions[0].id);
    }
  }, [versions, selectedVersionId]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Clock className="h-5 w-5 animate-spin mr-2" />
        Loading version history...
      </div>
    );
  }

  if (isError || versions.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <History className="h-10 w-10 mx-auto mb-3 opacity-50" />
        <p className="font-medium">No version history available</p>
        <p className="text-sm mt-1">Changes will be tracked after the first update</p>
      </div>
    );
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const getChangeTypeBadge = (type?: string) => {
    switch (type) {
      case "create":
        return "bg-green-500/20 text-green-400 border-green-500/30";
      case "activate":
        return "bg-cyan-500/20 text-cyan-400 border-cyan-500/30";
      case "deactivate":
        return "bg-gray-500/20 text-gray-400 border-gray-500/30";
      case "rollback":
        return "bg-amber-500/20 text-amber-400 border-amber-500/30";
      case "update":
      default:
        return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    }
  };

  const handleCompareSelect = (versionNumber: number) => {
    if (compareVersionA === null) {
      setCompareVersionA(versionNumber);
    } else if (compareVersionB === null && versionNumber !== compareVersionA) {
      setCompareVersionB(versionNumber);
    } else {
      // Reset and start over
      setCompareVersionA(versionNumber);
      setCompareVersionB(null);
    }
  };

  return (
    <div className="flex gap-4 flex-1 min-h-0">
      {/* Version List - Left Panel */}
      <div className="w-72 flex-shrink-0 flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-medium flex items-center gap-2">
            <History className="h-4 w-4 text-primary" />
            Versions
          </h4>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs">
              {versions.length}
            </Badge>
            <Button
              variant={compareMode ? "default" : "ghost"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                setCompareMode(!compareMode);
                setCompareVersionA(null);
                setCompareVersionB(null);
              }}
            >
              <ArrowLeftRight className="h-3 w-3 mr-1" />
              Compare
            </Button>
          </div>
        </div>

        {compareMode && (
          <div className="mb-3 p-2 rounded-lg bg-primary/5 border border-primary/20 text-xs">
            <p className="text-muted-foreground">
              {compareVersionA === null
                ? "Select first version to compare"
                : compareVersionB === null
                ? `v${compareVersionA} selected - now select second version`
                : `Comparing v${compareVersionA} → v${compareVersionB}`}
            </p>
            {(compareVersionA || compareVersionB) && (
              <Button
                variant="ghost"
                size="sm"
                className="h-5 text-xs mt-1 p-0"
                onClick={() => {
                  setCompareVersionA(null);
                  setCompareVersionB(null);
                }}
              >
                Clear selection
              </Button>
            )}
          </div>
        )}

        <ScrollArea className="flex-1">
          <div className="space-y-1.5 pr-3">
            {versions.map((version) => {
              const isCurrent = version.version_number === currentVersion;
              const isSelected = selectedVersionId === version.id;
              const isCompareSelected =
                compareMode &&
                (version.version_number === compareVersionA ||
                  version.version_number === compareVersionB);

              return (
                <div
                  key={version.id}
                  className={cn(
                    "rounded-lg border p-2.5 transition-all cursor-pointer",
                    isSelected && !compareMode
                      ? "border-primary bg-primary/5"
                      : isCompareSelected
                      ? "border-amber-500 bg-amber-500/10"
                      : isCurrent
                      ? "border-green-500/30 bg-green-500/5"
                      : "border-border hover:border-primary/50"
                  )}
                  onClick={() => {
                    if (compareMode) {
                      handleCompareSelect(version.version_number);
                    } else {
                      setSelectedVersionId(version.id);
                    }
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">v{version.version_number}</span>
                      {isCurrent && (
                        <Badge className="bg-green-500/20 text-green-400 border-green-500/30 text-[10px] px-1">
                          Current
                        </Badge>
                      )}
                    </div>
                    <Badge className={cn("text-[10px] px-1.5", getChangeTypeBadge(version.change_type))}>
                      {version.change_type || "update"}
                    </Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-1">{formatDate(version.created_at)}</p>
                  {version.was_activated && !isCurrent && (
                    <div className="flex items-center gap-1 mt-1 text-[10px] text-muted-foreground">
                      <Zap className="h-2.5 w-2.5" />
                      Was active
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </ScrollArea>

        <Separator className="my-3" />

        <div className="text-[11px] text-muted-foreground space-y-1">
          <p className="flex items-center gap-1">
            <Check className="h-3 w-3 text-green-400" />
            Auto-versioned on every save
          </p>
        </div>
      </div>

      {/* Detail Panel - Right Side */}
      <div className="flex-1 border-l border-border pl-4 flex flex-col min-w-0">
        {compareMode && compareVersionA && compareVersionB ? (
          <VersionCompare
            botId={botId || ""}
            configId={configId}
            versionA={compareVersionA}
            versionB={compareVersionB}
          />
        ) : selectedVersion ? (
          <VersionDetail
            version={selectedVersion}
            isCurrent={selectedVersion.version_number === currentVersion}
            onRollback={onRollback}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <p>Select a version to view details</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// VERSION DETAIL PANEL
// ═══════════════════════════════════════════════════════════════

interface VersionDetailProps {
  version: ConfigVersion;
  isCurrent: boolean;
  onRollback?: (version: ConfigVersion) => void;
}

function VersionDetail({ version, isCurrent, onRollback }: VersionDetailProps) {
  const [activeTab, setActiveTab] = useState("overview");

  const copyToClipboard = (data: unknown, label: string) => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    toast.success(`${label} copied to clipboard`);
  };

  // Build full config object for JSON view
  const fullConfig = {
    version: version.version_number,
    trading_capital_usd: version.trading_capital_usd,
    enabled_symbols: version.enabled_symbols,
    risk_config: version.risk_config,
    execution_config: version.execution_config,
    profile_overrides: version.profile_overrides,
    change_type: version.change_type,
    change_summary: version.change_summary,
    was_activated: version.was_activated,
    activated_at: version.activated_at,
    created_at: version.created_at,
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-semibold">v{version.version_number}</span>
          {isCurrent && (
            <Badge className="bg-green-500/20 text-green-400 border-green-500/30">Current</Badge>
          )}
          <Badge className={cn("text-xs", getChangeTypeBadgeStatic(version.change_type))}>
            {version.change_type || "update"}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => copyToClipboard(fullConfig, "Full config")}
          >
            <Copy className="h-4 w-4 mr-1" />
            Copy JSON
          </Button>
          {onRollback && !isCurrent && (
            <Button variant="outline" size="sm" onClick={() => onRollback(version)}>
              <RotateCcw className="h-4 w-4 mr-1" />
              Rollback to this version
            </Button>
          )}
        </div>
      </div>

      <p className="text-sm text-muted-foreground mb-4">
        {new Date(version.created_at).toLocaleString()}
        {version.change_summary && ` — ${version.change_summary}`}
      </p>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
        <TabsList className="w-full justify-start flex-shrink-0">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="risk">Risk Config</TabsTrigger>
          <TabsTrigger value="execution">Execution Config</TabsTrigger>
          <TabsTrigger value="full">Full JSON</TabsTrigger>
        </TabsList>

        <ScrollArea className="flex-1 mt-4 min-h-0">
          <TabsContent value="overview" className="mt-0 space-y-4 pr-4">
            {/* Capital & Symbols */}
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground mb-1">Trading Capital</p>
                <p className="font-mono text-lg">
                  ${version.trading_capital_usd?.toLocaleString() || "—"}
                </p>
              </div>
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground mb-1">Symbols</p>
                <p className="font-mono text-lg">{version.enabled_symbols?.length || 0}</p>
              </div>
            </div>

            {/* Symbols List */}
            {version.enabled_symbols && version.enabled_symbols.length > 0 && (
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground mb-2">Enabled Symbols</p>
                <div className="flex flex-wrap gap-1.5">
                  {version.enabled_symbols.map((symbol) => (
                    <Badge key={symbol} variant="outline" className="font-mono text-xs">
                      {symbol.replace("-USDT-SWAP", "")}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Quick Risk Summary */}
            {version.risk_config && (
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground mb-2">Risk Parameters</p>
                <div className="grid grid-cols-3 gap-3 text-sm">
                  {Object.entries(version.risk_config).slice(0, 6).map(([key, value]) => (
                    <div key={key}>
                      <span className="text-muted-foreground">{formatKey(key)}:</span>
                      <span className="ml-1 font-mono">{formatValue(value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="risk" className="mt-0 pr-4">
            <JsonViewer data={version.risk_config} title="Risk Configuration" />
          </TabsContent>

          <TabsContent value="execution" className="mt-0 pr-4">
            <JsonViewer data={version.execution_config} title="Execution Configuration" />
          </TabsContent>

          <TabsContent value="full" className="mt-0 pr-4">
            <JsonViewer data={fullConfig} title="Complete Version Snapshot" />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// VERSION COMPARE
// ═══════════════════════════════════════════════════════════════

interface VersionCompareProps {
  botId: string;
  configId: string;
  versionA: number;
  versionB: number;
}

function VersionCompare({ botId, configId, versionA, versionB }: VersionCompareProps) {
  const { data, isLoading, isError } = useCompareBotExchangeConfigVersions(
    botId,
    configId,
    Math.min(versionA, versionB),
    Math.max(versionA, versionB)
  );

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <Clock className="h-5 w-5 animate-spin mr-2" />
        Loading comparison...
      </div>
    );
  }

  if (isError || !data?.diff) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <p>Failed to load comparison</p>
      </div>
    );
  }

  const { diff } = data;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="font-semibold flex items-center gap-2">
          <ArrowLeftRight className="h-4 w-4" />
          Comparing v{Math.min(versionA, versionB)} → v{Math.max(versionA, versionB)}
        </h3>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="space-y-4">
          {diff.changes && diff.changes.length > 0 ? (
            diff.changes.map((change: any, index: number) => (
              <div key={index} className="rounded-lg border border-border p-3">
                <p className="text-sm font-medium text-primary mb-2">{change.label || change.field}</p>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div className="rounded bg-red-500/10 p-2">
                    <p className="text-[10px] text-red-400 mb-1">v{Math.min(versionA, versionB)}</p>
                    <pre className="font-mono text-xs whitespace-pre-wrap text-red-300">
                      {JSON.stringify(change.from, null, 2)}
                    </pre>
                  </div>
                  <div className="rounded bg-green-500/10 p-2">
                    <p className="text-[10px] text-green-400 mb-1">v{Math.max(versionA, versionB)}</p>
                    <pre className="font-mono text-xs whitespace-pre-wrap text-green-300">
                      {JSON.stringify(change.to, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <Check className="h-8 w-8 mx-auto mb-2 text-green-400" />
              <p>No differences found between these versions</p>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// JSON VIEWER
// ═══════════════════════════════════════════════════════════════

interface JsonViewerProps {
  data: unknown;
  title?: string;
}

function JsonViewer({ data, title }: JsonViewerProps) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  if (!data || (typeof data === "object" && Object.keys(data as object).length === 0)) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <FileJson className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p>No data available</p>
      </div>
    );
  }

  const copyToClipboard = () => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    toast.success("Copied to clipboard");
  };

  const toggleCollapse = (key: string) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const renderValue = (value: unknown, key: string, depth: number = 0): React.ReactNode => {
    if (value === null || value === undefined) {
      return <span className="text-gray-500">null</span>;
    }

    if (typeof value === "boolean") {
      return <span className={value ? "text-green-400" : "text-red-400"}>{String(value)}</span>;
    }

    if (typeof value === "number") {
      return <span className="text-cyan-400">{value}</span>;
    }

    if (typeof value === "string") {
      return <span className="text-amber-400">"{value}"</span>;
    }

    if (Array.isArray(value)) {
      if (value.length === 0) return <span className="text-gray-500">[]</span>;
      const isCollapsed = collapsed[key];
      return (
        <div>
          <button
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
            onClick={() => toggleCollapse(key)}
          >
            {isCollapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            <span className="text-purple-400">[{value.length}]</span>
          </button>
          {!isCollapsed && (
            <div className="ml-4 border-l border-border/50 pl-3 mt-1 space-y-0.5">
              {value.map((item, i) => (
                <div key={i} className="flex">
                  <span className="text-muted-foreground mr-2">{i}:</span>
                  {renderValue(item, `${key}.${i}`, depth + 1)}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    if (typeof value === "object") {
      const entries = Object.entries(value as object);
      if (entries.length === 0) return <span className="text-gray-500">{"{}"}</span>;
      const isCollapsed = collapsed[key];
      return (
        <div>
          <button
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
            onClick={() => toggleCollapse(key)}
          >
            {isCollapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            <span className="text-purple-400">{"{"}...{"}"}</span>
          </button>
          {!isCollapsed && (
            <div className="ml-4 border-l border-border/50 pl-3 mt-1 space-y-0.5">
              {entries.map(([k, v]) => (
                <div key={k} className="flex">
                  <span className="text-blue-400 mr-1">"{k}":</span>
                  {renderValue(v, `${key}.${k}`, depth + 1)}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    return <span>{String(value)}</span>;
  };

  return (
    <div className="rounded-lg border border-border bg-black/20">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <Code className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">{title || "JSON"}</span>
        </div>
        <Button variant="ghost" size="sm" className="h-7" onClick={copyToClipboard}>
          <Copy className="h-3 w-3 mr-1" />
          Copy
        </Button>
      </div>
      <div className="p-3 font-mono text-xs overflow-x-auto">
        {typeof data === "object" && data !== null ? (
          <div className="space-y-0.5">
            {Object.entries(data as object).map(([key, value]) => (
              <div key={key} className="flex">
                <span className="text-blue-400 mr-1">"{key}":</span>
                {renderValue(value, key)}
              </div>
            ))}
          </div>
        ) : (
          <pre>{JSON.stringify(data, null, 2)}</pre>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function getChangeTypeBadgeStatic(type?: string) {
  switch (type) {
    case "create":
      return "bg-green-500/20 text-green-400 border-green-500/30";
    case "activate":
      return "bg-cyan-500/20 text-cyan-400 border-cyan-500/30";
    case "deactivate":
      return "bg-gray-500/20 text-gray-400 border-gray-500/30";
    case "rollback":
      return "bg-amber-500/20 text-amber-400 border-amber-500/30";
    case "update":
    default:
      return "bg-blue-500/20 text-blue-400 border-blue-500/30";
  }
}

function formatKey(key: string): string {
  return key
    .replace(/([A-Z])/g, " $1")
    .replace(/_/g, " ")
    .replace(/^./, (str) => str.toUpperCase())
    .trim();
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
