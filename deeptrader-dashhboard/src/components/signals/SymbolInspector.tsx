import { useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useSymbolDecisions } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { SymbolStatus } from "../../lib/api/types";
import { 
  CheckCircle2, 
  XCircle, 
  Clock, 
  ChevronDown, 
  ChevronRight,
  ExternalLink,
  Settings,
  Power,
  History
} from "lucide-react";
import { cn } from "../../lib/utils";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

interface SymbolInspectorProps {
  symbol: SymbolStatus | null;
  onClose: () => void;
}

function formatTimeAgo(timestamp: string | null): string {
  if (!timestamp) return "—";
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return timestamp;
  }
}

function DecisionRow({ decision, expanded, onToggle }: { decision: any; expanded: boolean; onToggle: () => void }) {
  const isAccepted = decision.outcome === "approved" || decision.outcome === "accepted";
  
  return (
    <div className="border rounded-lg">
      <div 
        className="flex items-center gap-3 p-3 cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={onToggle}
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
        {isAccepted ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
        ) : (
          <XCircle className="h-4 w-4 text-red-500 shrink-0" />
        )}
        <span className="font-mono text-xs text-muted-foreground">{formatTimeAgo(decision.timestamp)}</span>
        <Badge variant="outline" className={cn(
          "text-[10px]",
          isAccepted ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
        )}>
          {decision.outcome}
        </Badge>
        {decision.rejectionStage && (
          <Badge variant="outline" className="text-[10px] border-red-500/50 text-red-500">
            {decision.rejectionStage.replace(/_/g, " ")}
          </Badge>
        )}
        <span className="text-xs text-muted-foreground truncate flex-1">{decision.rejectionReason || "—"}</span>
        <span className="font-mono text-xs text-muted-foreground">{decision.latency}ms</span>
      </div>
      
      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t bg-muted/20">
          {/* Thresholds vs Actuals */}
          {(Object.keys(decision.thresholds).length > 0 || Object.keys(decision.actuals).length > 0) && (
            <div className="grid grid-cols-2 gap-2 pt-2">
              {Object.entries(decision.thresholds).map(([key, threshold]) => {
                const actual = decision.actuals[key];
                const exceeded = typeof actual === "number" && typeof threshold === "number" && actual > threshold;
                return (
                  <div key={key} className="text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground capitalize">{key.replace(/([A-Z])/g, " $1").trim()}:</span>
                      <div className="flex items-center gap-2">
                        <span className={cn("font-mono", exceeded && "text-red-500")}>
                          {typeof actual === "number" ? actual.toFixed(4) : actual || "—"}
                        </span>
                        <span className="text-muted-foreground">/</span>
                        <span className="font-mono text-muted-foreground">
                          {typeof threshold === "number" ? threshold.toFixed(4) : threshold || "—"}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          
          {/* Stage Timings */}
          {Object.keys(decision.stageTimings).length > 0 && (
            <div className="pt-2 border-t">
              <div className="text-xs font-medium mb-1">Stage Timings:</div>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(decision.stageTimings).map(([stage, timing]) => (
                  <div key={stage} className="text-xs">
                    <span className="text-muted-foreground capitalize">{stage.replace(/_/g, " ")}:</span>
                    <span className="font-mono ml-1">{typeof timing === "number" ? `${timing.toFixed(2)}ms` : timing}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Signal Details */}
          {decision.signal.side && (
            <div className="pt-2 border-t">
              <div className="text-xs">
                <span className="text-muted-foreground">Signal: </span>
                <Badge variant="outline" className={cn(
                  "text-[10px]",
                  decision.signal.side === "long" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                )}>
                  {decision.signal.side}
                </Badge>
                <span className="ml-2 text-muted-foreground">
                  Strength: {decision.signal.strength?.toFixed(2) || "0.00"} 
                  {" "}(Confidence: {(decision.signal.confidence * 100).toFixed(0)}%)
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SymbolInspector({ symbol, onClose }: SymbolInspectorProps) {
  const { botId, exchangeAccountId } = useScopeStore();
  const [expandedDecisions, setExpandedDecisions] = useState<Set<string>>(new Set());
  
  const { data: decisionsData, isLoading } = useSymbolDecisions(
    symbol?.symbol || null,
    { botId: botId || undefined, exchangeAccountId: exchangeAccountId || undefined }
  );

  if (!symbol) return null;

  const toggleDecision = (id: string) => {
    const newExpanded = new Set(expandedDecisions);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedDecisions(newExpanded);
  };

  const decisions = decisionsData?.decisions || [];
  const hasSignal = symbol.signal.side !== null;

  return (
    <Sheet open={!!symbol} onOpenChange={onClose}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <SheetTitle>{symbol.symbol}</SheetTitle>
            <Badge variant="outline" className={cn(
              "text-xs",
              symbol.status === "tradable" && "border-emerald-500/50 text-emerald-500",
              symbol.status === "blocked" && "border-red-500/50 text-red-500",
              symbol.status === "no_signal" && "border-muted-foreground/50 text-muted-foreground"
            )}>
              {symbol.status}
            </Badge>
          </div>
          <SheetDescription>Symbol diagnostics and decision history</SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          <Tabs defaultValue="decisions" className="w-full">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="decisions">Decisions</TabsTrigger>
              <TabsTrigger value="snapshot">Snapshot</TabsTrigger>
              <TabsTrigger value="actions">Actions</TabsTrigger>
            </TabsList>

            {/* Decisions Tab */}
            <TabsContent value="decisions" className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium">Last 20 Decisions</h3>
                  {isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
                </div>
                {decisions.length === 0 ? (
                  <div className="text-center py-8 text-sm text-muted-foreground">
                    No decisions found for this symbol
                  </div>
                ) : (
                  <div className="space-y-2">
                    {decisions.map((decision) => (
                      <DecisionRow
                        key={decision.id}
                        decision={decision}
                        expanded={expandedDecisions.has(decision.id)}
                        onToggle={() => toggleDecision(decision.id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            </TabsContent>

            {/* Snapshot Tab */}
            <TabsContent value="snapshot" className="space-y-4">
              <Card>
                <CardContent className="p-4 space-y-4">
                  {/* Current Signal */}
                  <div>
                    <h4 className="text-xs font-medium mb-2">Current Signal</h4>
                    {hasSignal ? (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className={cn(
                            "text-xs",
                            symbol.signal.side === "long" ? "border-emerald-500/50 text-emerald-500" : "border-red-500/50 text-red-500"
                          )}>
                            {symbol.signal.side}
                          </Badge>
                          <span className="text-sm font-mono">Strength: {symbol.signal.strength?.toFixed(2) || "0.00"}</span>
                          <span className="text-sm text-muted-foreground">
                            Confidence: {(symbol.signal.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No signal (neutral)</p>
                    )}
                  </div>

                  {/* Active Profile */}
                  <div>
                    <h4 className="text-xs font-medium mb-2">Active Profile</h4>
                    <Badge variant="outline" className="text-xs">{symbol.profile || "Unknown"}</Badge>
                  </div>

                  {/* Blocking Info */}
                  {symbol.blockingStage && (
                    <div>
                      <h4 className="text-xs font-medium mb-2">Blocking Stage</h4>
                      <div className="space-y-1">
                        <Badge variant="outline" className="text-xs border-red-500/50 text-red-500">
                          {symbol.blockingStage.replace(/_/g, " ")}
                        </Badge>
                        {symbol.blockingReason && (
                          <p className="text-xs text-muted-foreground">{symbol.blockingReason}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Latency */}
                  <div>
                    <h4 className="text-xs font-medium mb-2">Latency</h4>
                    <p className="text-sm font-mono">
                      p95: <span className={cn(symbol.latencyP95 > 50 && "text-amber-500")}>
                        {symbol.latencyP95 > 0 ? `${symbol.latencyP95}ms` : "—"}
                      </span>
                    </p>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* Actions Tab */}
            <TabsContent value="actions" className="space-y-4">
              <Card>
                <CardContent className="p-4 space-y-3">
                  <h4 className="text-sm font-medium mb-3">Quick Actions</h4>
                  
                  {symbol.blockingStage === "spread_filter" && (
                    <Button variant="outline" className="w-full justify-start" size="sm">
                      <Settings className="h-4 w-4 mr-2" />
                      Temporarily relax spread filter for 10m
                    </Button>
                  )}
                  
                  <Button variant="outline" className="w-full justify-start" size="sm">
                    <Settings className="h-4 w-4 mr-2" />
                    Switch profile
                  </Button>
                  
                  <Button variant="outline" className="w-full justify-start" size="sm">
                    <Power className="h-4 w-4 mr-2" />
                    Disable symbol
                  </Button>
                  
                  <Link to={`/dashboard/replay-studio?symbol=${symbol.symbol}`}>
                    <Button variant="outline" className="w-full justify-start" size="sm">
                      <History className="h-4 w-4 mr-2" />
                      Open in Replay at last reject
                    </Button>
                  </Link>
                  
                  <Link to={`/dashboard/market-context?symbol=${symbol.symbol}`}>
                    <Button variant="outline" className="w-full justify-start" size="sm">
                      <ExternalLink className="h-4 w-4 mr-2" />
                      View Market Context
                    </Button>
                  </Link>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </SheetContent>
    </Sheet>
  );
}






