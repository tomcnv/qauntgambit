/**
 * RegimeTimeline - Timeline of regime shifts and anomalies
 * 
 * Features:
 * - Real-time regime events from rejections, health, and symbol anomalies
 * - Severity badges
 * - Click to filter Symbol Board
 * - Affected symbols as tags
 * - Link to Replay Studio
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  Filter,
  Info,
  Layers,
  Scale,
  TrendingUp,
  Wifi,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import type { RegimeEvent } from "./types";

// ============================================================================
// TYPES
// ============================================================================

interface RegimeTimelineProps {
  events: RegimeEvent[];
  onEventClick?: (event: RegimeEvent) => void;
  onSymbolFilter?: (symbols: string[]) => void;
  className?: string;
}

// ============================================================================
// EVENT TYPE CONFIG
// ============================================================================

const eventTypeConfig: Record<RegimeEvent['type'], {
  icon: React.ElementType;
  color: string;
  label: string;
  description: string;
}> = {
  spread: { 
    icon: Scale, 
    color: "text-blue-500", 
    label: "Spread",
    description: "Spread regime changes (widening/narrowing)"
  },
  volatility: { 
    icon: Activity, 
    color: "text-purple-500", 
    label: "Volatility",
    description: "Volatility regime shifts (spikes/calm)"
  },
  liquidity: { 
    icon: Layers, 
    color: "text-cyan-500", 
    label: "Liquidity",
    description: "Liquidity changes (thin/deep)"
  },
  funding: { 
    icon: TrendingUp, 
    color: "text-green-500", 
    label: "Funding",
    description: "Funding rate anomalies"
  },
  venue: { 
    icon: Wifi, 
    color: "text-orange-500", 
    label: "Venue",
    description: "Exchange/venue health issues"
  },
  anomaly: { 
    icon: AlertTriangle, 
    color: "text-amber-500", 
    label: "Anomaly",
    description: "General market anomalies"
  },
};

const severityConfig: Record<RegimeEvent['severity'], {
  bg: string;
  border: string;
  text: string;
  description: string;
}> = {
  info: { 
    bg: "bg-blue-500/10", 
    border: "border-blue-500/20", 
    text: "text-blue-500",
    description: "Informational events"
  },
  warning: { 
    bg: "bg-amber-500/10", 
    border: "border-amber-500/20", 
    text: "text-amber-500",
    description: "Warning - may impact trading"
  },
  critical: { 
    bg: "bg-red-500/10", 
    border: "border-red-500/20", 
    text: "text-red-500",
    description: "Critical - trading blocked"
  },
};

// ============================================================================
// EVENT ROW
// ============================================================================

function EventRow({ 
  event, 
  onEventClick, 
  onSymbolFilter,
}: { 
  event: RegimeEvent;
  onEventClick?: (event: RegimeEvent) => void;
  onSymbolFilter?: (symbols: string[]) => void;
}) {
  const typeConfig = eventTypeConfig[event.type];
  const sevConfig = severityConfig[event.severity];
  const Icon = typeConfig.icon;
  
  return (
    <div
      className={cn(
        "flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors",
        sevConfig.bg,
        "hover:brightness-95 dark:hover:brightness-110"
      )}
      onClick={() => onEventClick?.(event)}
    >
      {/* Icon */}
      <div className={cn(
        "p-1.5 rounded-full shrink-0",
        sevConfig.bg,
        sevConfig.border,
        "border"
      )}>
        <Icon className={cn("h-3.5 w-3.5", typeConfig.color)} />
      </div>
      
      {/* Content */}
      <div className="flex-1 min-w-0 space-y-1">
        {/* Header */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-muted-foreground">
            {event.time}
          </span>
          <Badge 
            variant="outline" 
            className={cn("text-[9px] px-1 py-0", sevConfig.text, sevConfig.border)}
          >
            {typeConfig.label}
          </Badge>
        </div>
        
        {/* Title & Message */}
        <div>
          <span className="text-xs font-medium">{event.title}</span>
          {event.message && event.message !== event.title && (
            <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">
              {event.message}
            </p>
          )}
        </div>
        
        {/* Previous → New Value */}
        {event.previousValue && event.newValue && (
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="text-muted-foreground">{event.previousValue}</span>
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
            <span className={sevConfig.text}>{event.newValue}</span>
          </div>
        )}
        
        {/* Affected Symbols */}
        {event.symbols.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {event.symbols.slice(0, 4).map((symbol) => (
              <Badge 
                key={symbol}
                variant="outline" 
                className="text-[9px] px-1 py-0 cursor-pointer hover:bg-muted"
                onClick={(e) => {
                  e.stopPropagation();
                  onSymbolFilter?.([symbol]);
                }}
              >
                {symbol}
              </Badge>
            ))}
            {event.symbols.length > 4 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="outline" className="text-[9px] px-1 py-0">
                    +{event.symbols.length - 4} more
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  {event.symbols.slice(4).join(', ')}
                </TooltipContent>
              </Tooltip>
            )}
            {event.symbols.length > 1 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-4 px-1 text-[9px]"
                onClick={(e) => {
                  e.stopPropagation();
                  onSymbolFilter?.(event.symbols);
                }}
              >
                <Filter className="h-2.5 w-2.5 mr-0.5" />
                Filter
              </Button>
            )}
          </div>
        )}
      </div>
      
      {/* Replay Link */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Link 
            to={`/analysis/replay?time=${new Date(event.timestamp).toISOString()}&symbol=${event.symbols[0] || ''}`}
            onClick={(e) => e.stopPropagation()}
          >
            <Button variant="ghost" size="sm" className="h-6 w-6 p-0 shrink-0">
              <ExternalLink className="h-3 w-3" />
            </Button>
          </Link>
        </TooltipTrigger>
        <TooltipContent>Open in Replay Studio</TooltipContent>
      </Tooltip>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function RegimeTimeline({ 
  events, 
  onEventClick, 
  onSymbolFilter,
  className,
}: RegimeTimelineProps) {
  const [filterType, setFilterType] = useState<RegimeEvent['type'] | 'all'>('all');
  const [filterSeverity, setFilterSeverity] = useState<RegimeEvent['severity'] | 'all'>('all');
  
  // Filter events
  const filteredEvents = events.filter(e => {
    if (filterType !== 'all' && e.type !== filterType) return false;
    if (filterSeverity !== 'all' && e.severity !== filterSeverity) return false;
    return true;
  });
  
  // Count by severity
  const criticalCount = events.filter(e => e.severity === 'critical').length;
  const warningCount = events.filter(e => e.severity === 'warning').length;
  const infoCount = events.filter(e => e.severity === 'info').length;
  
  // Count by type
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    events.forEach(e => {
      counts[e.type] = (counts[e.type] || 0) + 1;
    });
    return counts;
  }, [events]);
  
  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-medium">Regime Shifts & Anomalies</CardTitle>
            {criticalCount > 0 && (
              <Badge variant="outline" className="text-[10px] border-red-500/50 text-red-500">
                {criticalCount} critical
              </Badge>
            )}
            {warningCount > 0 && criticalCount === 0 && (
              <Badge variant="outline" className="text-[10px] border-amber-500/50 text-amber-500">
                {warningCount} warning
              </Badge>
            )}
          </div>
          
          <span className="text-[10px] text-muted-foreground">Last 24h</span>
        </div>
        
        {/* Filters - Compact dropdown style for narrow widths */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mt-2">
          {/* Type Filter - Icons only */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground shrink-0">Type:</span>
            <div className="flex gap-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    className={cn(
                      "h-5 px-1.5 text-[10px] rounded transition-colors",
                      filterType === 'all' 
                        ? "bg-primary text-primary-foreground" 
                        : "text-muted-foreground hover:text-foreground hover:bg-muted"
                    )}
                    onClick={() => setFilterType('all')}
                  >
                    All
                  </button>
                </TooltipTrigger>
                <TooltipContent>Show all event types</TooltipContent>
              </Tooltip>
              {Object.entries(eventTypeConfig).map(([type, config]) => {
                const count = typeCounts[type] || 0;
                const isActive = filterType === type;
                return (
                  <Tooltip key={type}>
                    <TooltipTrigger asChild>
                      <button
                        className={cn(
                          "h-5 w-5 rounded flex items-center justify-center transition-colors",
                          isActive 
                            ? "bg-primary text-primary-foreground" 
                            : "text-muted-foreground hover:text-foreground hover:bg-muted"
                        )}
                        onClick={() => setFilterType(type as RegimeEvent['type'])}
                      >
                        <config.icon className={cn("h-3 w-3", !isActive && config.color)} />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <div className="text-xs">
                        <div className="font-medium">{config.label} ({count})</div>
                        <div className="text-muted-foreground">{config.description}</div>
                      </div>
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
          </div>
          
          {/* Severity Filter - Compact badges */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground shrink-0">Severity:</span>
            <div className="flex gap-0.5">
              {(['all', 'critical', 'warning', 'info'] as const).map((sev) => {
                const isActive = filterSeverity === sev;
                const count = sev === 'critical' ? criticalCount : sev === 'warning' ? warningCount : sev === 'info' ? infoCount : 0;
                return (
                  <Tooltip key={sev}>
                    <TooltipTrigger asChild>
                      <button
                        className={cn(
                          "h-5 px-1.5 text-[10px] rounded transition-colors flex items-center gap-1",
                          isActive && sev === 'all' && "bg-primary text-primary-foreground",
                          isActive && sev === 'critical' && "bg-red-500 text-white",
                          isActive && sev === 'warning' && "bg-amber-500 text-white",
                          isActive && sev === 'info' && "bg-blue-500 text-white",
                          !isActive && "text-muted-foreground hover:text-foreground hover:bg-muted"
                        )}
                        onClick={() => setFilterSeverity(sev)}
                      >
                        {sev === 'all' ? 'All' : sev.charAt(0).toUpperCase()}
                        {sev !== 'all' && count > 0 && (
                          <span className="opacity-80">{count}</span>
                        )}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {sev === 'all' 
                        ? "Show all severity levels" 
                        : `${sev.charAt(0).toUpperCase() + sev.slice(1)} (${count})`}
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="p-2 space-y-2 max-h-[400px] overflow-y-auto">
        {filteredEvents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Info className="h-8 w-8 text-muted-foreground/30 mb-2" />
            <p className="text-sm text-muted-foreground">No regime events</p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              {events.length === 0 
                ? "Market conditions are stable. Events will appear when regime shifts or anomalies are detected."
                : "No events match the current filters. Try adjusting the type or severity filters."}
            </p>
          </div>
        ) : (
          filteredEvents.map((event) => (
            <EventRow 
              key={event.id} 
              event={event} 
              onEventClick={onEventClick}
              onSymbolFilter={onSymbolFilter}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}
