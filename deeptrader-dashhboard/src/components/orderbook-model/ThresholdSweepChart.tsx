/**
 * ThresholdSweepChart - Shows how different thresholds affect filter performance
 */

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Button } from "../ui/button";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { ThresholdSweepPoint } from "../../types/orderbookModel";

interface ThresholdSweepChartProps {
  data: ThresholdSweepPoint[] | undefined;
  isLoading?: boolean;
}

export function ThresholdSweepChart({ data, isLoading }: ThresholdSweepChartProps) {
  const [thresholdType, setThresholdType] = useState<
    "min_confidence" | "min_predicted_move_bps"
  >("min_confidence");

  const chartData =
    data
      ?.filter((p) => p.threshold_type === thresholdType)
      .map((p) => ({
        x: thresholdType === "min_confidence" ? p.x * 100 : p.x,
        blockPrecision: p.block_precision_pct,
        missRate: p.miss_rate_pct,
        netSavings: p.net_savings_bps,
        n: p.n_candidates,
      })) ?? [];

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Threshold Sweep</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[200px] animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Threshold Sweep Analysis</CardTitle>
          <div className="flex rounded-lg border bg-muted/50 p-0.5">
            <Button
              variant={thresholdType === "min_confidence" ? "default" : "ghost"}
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={() => setThresholdType("min_confidence")}
            >
              Confidence
            </Button>
            <Button
              variant={thresholdType === "min_predicted_move_bps" ? "default" : "ghost"}
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={() => setThresholdType("min_predicted_move_bps")}
            >
              Move (bps)
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[200px]">
          {chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              Not enough data for threshold analysis
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="x"
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v) =>
                    thresholdType === "min_confidence" ? `${v}%` : `${v}bp`
                  }
                />
                <YAxis
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  width={40}
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.[0]) return null;
                    const data = payload[0].payload;
                    return (
                      <div className="bg-popover border rounded-lg shadow-lg p-3 text-xs">
                        <p className="font-medium">
                          {thresholdType === "min_confidence"
                            ? `Min Confidence: ${data.x}%`
                            : `Min Move: ${data.x} bps`}
                        </p>
                        <p className="text-emerald-600 mt-1">
                          Block Precision: {data.blockPrecision.toFixed(1)}%
                        </p>
                        <p className="text-red-500">
                          Miss Rate: {data.missRate.toFixed(1)}%
                        </p>
                        <p className="text-blue-500">
                          Net Savings: {data.netSavings.toFixed(1)} bps
                        </p>
                      </div>
                    );
                  }}
                />
                <Legend
                  verticalAlign="top"
                  height={24}
                  formatter={(value) => (
                    <span className="text-xs text-muted-foreground">{value}</span>
                  )}
                />
                <Line
                  type="monotone"
                  dataKey="blockPrecision"
                  name="Block Precision"
                  stroke="hsl(142 76% 36%)"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="missRate"
                  name="Miss Rate"
                  stroke="hsl(0 84% 60%)"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

