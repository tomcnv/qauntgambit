/**
 * Latency Chart Component
 *
 * Time-series visualization of latency metrics (p50/p95/p99).
 * Shows historical latency with configurable thresholds.
 */

import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts";
import { Activity, AlertTriangle, CheckCircle, TrendingUp } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";
import { Skeleton } from "../ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { cn } from "../../lib/utils";
import { useLatencyHistory, useLatencyOperations } from "../../lib/api/quant-hooks";
import { useState } from "react";

interface LatencyThresholds {
  warning: number;
  critical: number;
}

const DEFAULT_THRESHOLDS: Record<string, LatencyThresholds> = {
  tick_to_decision: { warning: 10, critical: 20 },
  tick_to_execution: { warning: 30, critical: 50 },
  order_send_to_ack: { warning: 80, critical: 150 },
  feature_to_decision: { warning: 8, critical: 15 },
  default: { warning: 20, critical: 50 },
};

function getThresholds(operation: string): LatencyThresholds {
  return DEFAULT_THRESHOLDS[operation] || DEFAULT_THRESHOLDS.default;
}

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface LatencyChartProps {
  className?: string;
  defaultOperation?: string;
  hours?: number;
  compact?: boolean;
}

export function LatencyChart({
  className,
  defaultOperation = "tick_to_decision",
  hours = 1,
  compact = false,
}: LatencyChartProps) {
  const [selectedOperation, setSelectedOperation] = useState(defaultOperation);
  const [selectedHours, setSelectedHours] = useState(hours);

  const { data: historyData, isLoading: historyLoading } = useLatencyHistory(
    selectedOperation,
    selectedHours
  );
  const { data: operationsData } = useLatencyOperations();

  const operations = operationsData?.operations || [];
  const history = historyData?.history || [];
  const thresholds = getThresholds(selectedOperation);

  const chartData = useMemo(() => {
    return history.map((point) => ({
      time: formatTime(point.timestamp),
      p50: point.p50_ms,
      p95: point.p95_ms,
      p99: point.p99_ms,
    }));
  }, [history]);

  // Calculate current status
  const latestPoint = history[history.length - 1];
  const currentP99 = latestPoint?.p99_ms ?? 0;
  const status =
    currentP99 >= thresholds.critical
      ? "critical"
      : currentP99 >= thresholds.warning
        ? "warning"
        : "healthy";

  if (compact) {
    return (
      <Card className={cn("", className)}>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Latency</span>
            </div>
            <Badge
              variant={
                status === "critical"
                  ? "destructive"
                  : status === "warning"
                    ? "outline"
                    : "secondary"
              }
              className={cn(
                "text-xs",
                status === "healthy" && "bg-emerald-500/10 text-emerald-600 border-emerald-500/30"
              )}
            >
              {status === "critical" && <AlertTriangle className="h-3 w-3 mr-1" />}
              {status === "warning" && <TrendingUp className="h-3 w-3 mr-1" />}
              {status === "healthy" && <CheckCircle className="h-3 w-3 mr-1" />}
              p99: {currentP99.toFixed(1)}ms
            </Badge>
          </div>

          {historyLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : chartData.length === 0 ? (
            <div className="h-24 flex items-center justify-center text-sm text-muted-foreground">
              No latency data available
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={100}>
              <LineChart data={chartData}>
                <Line
                  type="monotone"
                  dataKey="p99"
                  stroke="#ef4444"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="p50"
                  stroke="#22c55e"
                  dot={false}
                  strokeWidth={1}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={cn("", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-lg">Latency Metrics</CardTitle>
          </div>
          <Badge
            variant={
              status === "critical"
                ? "destructive"
                : status === "warning"
                  ? "outline"
                  : "secondary"
            }
            className={cn(
              status === "healthy" && "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
              status === "warning" && "bg-amber-500/10 text-amber-600 border-amber-500/30"
            )}
          >
            {status === "critical" && <AlertTriangle className="h-3 w-3 mr-1" />}
            {status === "warning" && <TrendingUp className="h-3 w-3 mr-1" />}
            {status === "healthy" && <CheckCircle className="h-3 w-3 mr-1" />}
            {status.charAt(0).toUpperCase() + status.slice(1)}
          </Badge>
        </div>
        <CardDescription>Real-time latency percentiles with SLO thresholds</CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Controls */}
        <div className="flex gap-3">
          <Select value={selectedOperation} onValueChange={setSelectedOperation}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="Select operation" />
            </SelectTrigger>
            <SelectContent>
              {operations.length > 0 ? (
                operations.map((op) => (
                  <SelectItem key={op.name} value={op.name}>
                    <div className="flex items-center justify-between w-full">
                      <span>{op.name.replace(/_/g, " ")}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        p99: {op.p99_ms.toFixed(1)}ms
                      </span>
                    </div>
                  </SelectItem>
                ))
              ) : (
                <SelectItem value={selectedOperation}>
                  {selectedOperation.replace(/_/g, " ")}
                </SelectItem>
              )}
            </SelectContent>
          </Select>

          <Select
            value={selectedHours.toString()}
            onValueChange={(v) => setSelectedHours(Number(v))}
          >
            <SelectTrigger className="w-[100px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">1 hour</SelectItem>
              <SelectItem value="2">2 hours</SelectItem>
              <SelectItem value="6">6 hours</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Current stats */}
        {latestPoint && (
          <div className="grid grid-cols-4 gap-3">
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground">p50</p>
              <p className="text-lg font-semibold text-emerald-600">
                {latestPoint.p50_ms.toFixed(1)}ms
              </p>
            </div>
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground">p95</p>
              <p className="text-lg font-semibold text-amber-600">
                {latestPoint.p95_ms.toFixed(1)}ms
              </p>
            </div>
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground">p99</p>
              <p
                className={cn(
                  "text-lg font-semibold",
                  currentP99 >= thresholds.critical
                    ? "text-red-600"
                    : currentP99 >= thresholds.warning
                      ? "text-amber-600"
                      : "text-emerald-600"
                )}
              >
                {latestPoint.p99_ms.toFixed(1)}ms
              </p>
            </div>
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground">samples</p>
              <p className="text-lg font-semibold">{latestPoint.count.toLocaleString()}</p>
            </div>
          </div>
        )}

        {/* Chart */}
        {historyLoading ? (
          <Skeleton className="h-[200px] w-full" />
        ) : chartData.length === 0 ? (
          <div className="h-[200px] flex items-center justify-center text-muted-foreground">
            No latency data available for the selected time range
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <XAxis
                dataKey="time"
                tick={{ fontSize: 10 }}
                interval="preserveStartEnd"
                stroke="#888888"
              />
              <YAxis
                tick={{ fontSize: 10 }}
                domain={[0, "auto"]}
                stroke="#888888"
                label={{
                  value: "ms",
                  angle: -90,
                  position: "insideLeft",
                  fontSize: 10,
                  fill: "#888888",
                }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "6px",
                }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="p50"
                stroke="#22c55e"
                dot={false}
                name="p50"
                strokeWidth={1.5}
              />
              <Line
                type="monotone"
                dataKey="p95"
                stroke="#f59e0b"
                dot={false}
                name="p95"
                strokeWidth={1.5}
              />
              <Line
                type="monotone"
                dataKey="p99"
                stroke="#ef4444"
                dot={false}
                strokeWidth={2}
                name="p99"
              />
              <ReferenceLine
                y={thresholds.warning}
                stroke="#f59e0b"
                strokeDasharray="3 3"
                label={{
                  value: "Warning",
                  fontSize: 10,
                  fill: "#f59e0b",
                  position: "right",
                }}
              />
              <ReferenceLine
                y={thresholds.critical}
                stroke="#ef4444"
                strokeDasharray="3 3"
                label={{
                  value: "Critical",
                  fontSize: 10,
                  fill: "#ef4444",
                  position: "right",
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}

        {/* SLO info */}
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="w-3 h-0.5 bg-amber-500" />
            Warning: {thresholds.warning}ms
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-0.5 bg-red-500" />
            Critical: {thresholds.critical}ms
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

export default LatencyChart;
