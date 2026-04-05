/**
 * RollingAccuracyChart - Line chart showing accuracy over time
 */

import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { AccuracyPoint } from "../../types/orderbookModel";
import { format } from "date-fns";

interface RollingAccuracyChartProps {
  data: AccuracyPoint[] | undefined;
  isLoading?: boolean;
}

export function RollingAccuracyChart({ data, isLoading }: RollingAccuracyChartProps) {
  const chartData = data?.map((point) => ({
    time: new Date(point.ts).getTime(),
    accuracy: point.rolling_accuracy_pct,
    validated: point.validated,
    made: point.made,
  })) ?? [];

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Rolling Accuracy</CardTitle>
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
        <CardTitle className="text-sm font-medium">Rolling Accuracy Over Time</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px]">
          {chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              No accuracy data yet. Model is warming up.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="time"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(ts) => format(new Date(ts), "HH:mm")}
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  width={40}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.[0]) return null;
                    const data = payload[0].payload;
                    return (
                      <div className="bg-popover border rounded-lg shadow-lg p-3 text-xs">
                        <p className="font-medium">
                          {format(new Date(data.time), "HH:mm:ss")}
                        </p>
                        <p className="text-primary mt-1">
                          Accuracy: {data.accuracy.toFixed(1)}%
                        </p>
                        <p className="text-muted-foreground">
                          {data.validated} validated / {data.made} made
                        </p>
                      </div>
                    );
                  }}
                />
                {/* 50% baseline */}
                <ReferenceLine
                  y={50}
                  stroke="hsl(var(--muted-foreground))"
                  strokeDasharray="3 3"
                  strokeOpacity={0.5}
                />
                <Line
                  type="monotone"
                  dataKey="accuracy"
                  stroke="hsl(var(--primary))"
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

