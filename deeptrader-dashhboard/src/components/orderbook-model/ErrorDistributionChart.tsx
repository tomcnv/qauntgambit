/**
 * ErrorDistributionChart - Histogram of prediction errors
 */

import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { ErrorDistribution } from "../../types/orderbookModel";

interface ErrorDistributionChartProps {
  data: ErrorDistribution | undefined;
  isLoading?: boolean;
}

export function ErrorDistributionChart({ data, isLoading }: ErrorDistributionChartProps) {
  const chartData =
    data?.histogram?.map((h) => ({
      bucket: h.bucket_center_bps,
      count: h.count,
    })) ?? [];

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Error Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[200px] animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  const meanError = data?.mean_error_bps ?? 0;
  const mae = data?.mae_bps ?? 0;
  const medianAbs = data?.median_abs_error_bps ?? 0;

  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">
            Error Distribution (Actual - Predicted)
          </CardTitle>
          <div className="flex gap-3 text-[10px] text-muted-foreground">
            <span>
              Mean: <span className="font-mono">{meanError.toFixed(1)}</span> bps
            </span>
            <span>
              MAE: <span className="font-mono">{mae.toFixed(1)}</span> bps
            </span>
            <span>
              Median: <span className="font-mono">{medianAbs.toFixed(1)}</span> bps
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[200px]">
          {chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              No error data available yet
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="bucket"
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v) => `${v}`}
                  label={{
                    value: "Error (bps)",
                    position: "bottom",
                    offset: -5,
                    fontSize: 10,
                  }}
                />
                <YAxis
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  width={35}
                  label={{
                    value: "Count",
                    angle: -90,
                    position: "insideLeft",
                    offset: 10,
                    fontSize: 10,
                  }}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.[0]) return null;
                    const data = payload[0].payload;
                    return (
                      <div className="bg-popover border rounded-lg shadow-lg p-3 text-xs">
                        <p className="font-medium">Error: {data.bucket} bps</p>
                        <p className="text-primary">Count: {data.count}</p>
                      </div>
                    );
                  }}
                />
                {/* Zero reference line */}
                <ReferenceLine x={0} stroke="hsl(var(--muted-foreground))" />
                {/* Mean error reference */}
                <ReferenceLine
                  x={meanError}
                  stroke="hsl(var(--primary))"
                  strokeDasharray="5 5"
                />
                <Bar
                  dataKey="count"
                  fill="hsl(var(--primary))"
                  opacity={0.7}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

