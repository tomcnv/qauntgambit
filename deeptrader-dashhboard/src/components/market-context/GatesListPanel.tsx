/**
 * GatesListPanel - Shows all gates with threshold vs actual values
 * 
 * Displays:
 * - Gate name
 * - Threshold value
 * - Actual value
 * - Status icon (check/warning/x)
 * - Expandable details
 */

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Filter,
  Info,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import { cn } from "../../lib/utils";
import type { GateStatus } from "./types";

// ============================================================================
// TYPES
// ============================================================================

interface GatesListPanelProps {
  gates: GateStatus[];
  className?: string;
}

// ============================================================================
// GATE ROW
// ============================================================================

function GateRow({ gate }: { gate: GateStatus }) {
  const [expanded, setExpanded] = useState(false);
  
  const StatusIcon = gate.unknown
    ? Info
    : gate.passed
    ? CheckCircle2
    : gate.severity === 'warning'
    ? AlertTriangle
    : XCircle;
  
  const statusColor = gate.unknown
    ? "text-slate-500"
    : gate.passed
    ? "text-emerald-500"
    : gate.severity === 'warning'
    ? "text-amber-500"
    : "text-red-500";
  
  const bgColor = gate.unknown
    ? "bg-slate-500/5 hover:bg-slate-500/10"
    : gate.passed
    ? "hover:bg-emerald-500/5"
    : gate.severity === 'warning'
    ? "bg-amber-500/5 hover:bg-amber-500/10"
    : "bg-red-500/5 hover:bg-red-500/10";
  
  return (
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <CollapsibleTrigger asChild>
        <div className={cn(
          "flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors",
          bgColor
        )}>
          {/* Status Icon */}
          <StatusIcon className={cn("h-4 w-4 shrink-0", statusColor)} />
          
          {/* Gate Name */}
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium">{gate.name}</span>
          </div>
          
          {/* Values */}
          <div className="flex items-center gap-4 text-xs">
            {/* Threshold */}
            <div className="text-right">
              <span className="text-muted-foreground">Target: </span>
              <span className="font-mono font-medium">
                {typeof gate.threshold === 'number' 
                  ? gate.threshold.toFixed(1) 
                  : gate.threshold}
                {gate.unit}
              </span>
            </div>
            
            {/* vs */}
            <span className="text-muted-foreground">vs</span>
            
            {/* Actual */}
            <div className="text-right min-w-[60px]">
              <span className={cn("font-mono font-medium", statusColor)}>
                {typeof gate.actual === 'number' 
                  ? gate.actual.toFixed(1) 
                  : gate.actual}
                {gate.unit}
              </span>
            </div>
          </div>
          
          {/* Expand Icon */}
          {gate.description && (
            <ChevronRight className={cn(
              "h-4 w-4 text-muted-foreground transition-transform",
              expanded && "rotate-90"
            )} />
          )}
        </div>
      </CollapsibleTrigger>
      
      {gate.description && (
        <CollapsibleContent>
          <div className="px-3 pb-2 pl-10">
            <p className="text-xs text-muted-foreground">{gate.description}</p>
          </div>
        </CollapsibleContent>
      )}
    </Collapsible>
  );
}

// ============================================================================
// SUMMARY BAR
// ============================================================================

function GatesSummary({ gates }: { gates: GateStatus[] }) {
  const passed = gates.filter(g => g.passed).length;
  const unknown = gates.filter(g => g.unknown).length;
  const warnings = gates.filter(g => !g.passed && !g.unknown && g.severity === 'warning').length;
  const failed = gates.filter(g => !g.passed && (g.blocking ?? g.severity === 'critical')).length;
  
  return (
    <div className="flex items-center gap-3 text-xs">
      <div className="flex items-center gap-1.5">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
        <span className="font-medium">{passed}</span>
        <span className="text-muted-foreground">passed</span>
      </div>
      {warnings > 0 && (
        <div className="flex items-center gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
          <span className="font-medium text-amber-500">{warnings}</span>
          <span className="text-muted-foreground">warning</span>
        </div>
      )}
      {unknown > 0 && (
        <div className="flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5 text-slate-500" />
          <span className="font-medium text-slate-500">{unknown}</span>
          <span className="text-muted-foreground">unknown</span>
        </div>
      )}
      {failed > 0 && (
        <div className="flex items-center gap-1.5">
          <XCircle className="h-3.5 w-3.5 text-red-500" />
          <span className="font-medium text-red-500">{failed}</span>
          <span className="text-muted-foreground">failed</span>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function GatesListPanel({ gates, className }: GatesListPanelProps) {
  const [showOnlyFailed, setShowOnlyFailed] = useState(false);
  
  const filteredGates = showOnlyFailed 
    ? gates.filter(g => !g.passed && (g.blocking ?? g.severity === 'critical'))
    : gates;
  
  const failedCount = gates.filter(g => !g.passed && (g.blocking ?? g.severity === 'critical')).length;
  
  // Group gates by category
  const dataGates = filteredGates.filter(g => 
    ['data_ready', 'feed_health'].includes(g.key)
  );
  const marketGates = filteredGates.filter(g => 
    ['spread_cap', 'vol_band', 'funding_cap', 'liquidity_min'].includes(g.key)
  );
  const executionGates = filteredGates.filter(g => 
    ['latency_cap', 'slippage_cap'].includes(g.key)
  );
  const riskGates = filteredGates.filter(g => 
    ['risk_policy', 'exposure_cap', 'daily_loss'].includes(g.key)
  );
  const otherGates = filteredGates.filter(g => 
    !['data_ready', 'feed_health', 'spread_cap', 'vol_band', 'funding_cap', 
      'liquidity_min', 'latency_cap', 'slippage_cap', 'risk_policy', 
      'exposure_cap', 'daily_loss'].includes(g.key)
  );
  
  const renderGateGroup = (title: string, groupGates: GateStatus[]) => {
    if (groupGates.length === 0) return null;
    
    return (
      <div className="space-y-1">
        <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider px-3 pt-2">
          {title}
        </h4>
        {groupGates.map(gate => (
          <GateRow key={gate.key} gate={gate} />
        ))}
      </div>
    );
  };
  
  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Trading Gates</CardTitle>
            {failedCount > 0 && (
              <Badge variant="outline" className="text-[10px] border-red-500/50 text-red-500">
                {failedCount} blocking
              </Badge>
            )}
          </div>
          
          <Button
            variant={showOnlyFailed ? "default" : "outline"}
            size="sm"
            className="h-6 text-[11px]"
            onClick={() => setShowOnlyFailed(!showOnlyFailed)}
          >
            <Filter className="h-3 w-3 mr-1" />
            {showOnlyFailed ? "Show All" : "Blocking Only"}
          </Button>
        </div>
        
        <GatesSummary gates={gates} />
      </CardHeader>
      
      <CardContent className="p-2 space-y-2">
        {filteredGates.length === 0 ? (
          <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            All gates passing
          </div>
        ) : (
          <>
            {renderGateGroup("Data & Feed", dataGates)}
            {renderGateGroup("Market Conditions", marketGates)}
            {renderGateGroup("Execution", executionGates)}
            {renderGateGroup("Risk Policy", riskGates)}
            {renderGateGroup("Other", otherGates)}
            
            {/* If no groups matched, show all */}
            {dataGates.length === 0 && marketGates.length === 0 && 
             executionGates.length === 0 && riskGates.length === 0 && 
             otherGates.length === 0 && (
              <div className="space-y-1">
                {filteredGates.map(gate => (
                  <GateRow key={gate.key} gate={gate} />
                ))}
              </div>
            )}
          </>
        )}
        
        {/* Info footer */}
        <div className="flex items-start gap-2 p-2 mt-2 rounded-lg bg-muted/30 text-[10px] text-muted-foreground">
          <Info className="h-3 w-3 shrink-0 mt-0.5" />
          <span>
            Gates are evaluated continuously. A failed gate will block new trades 
            but won't close existing positions.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
