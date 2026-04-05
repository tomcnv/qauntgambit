/**
 * PredVsActualScatter - Scatter plot of predicted vs actual moves
 */

import { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ZAxis,
} from "recharts";
import type { PredActualPoint } from "../../types/orderbookModel";
import { format } from "date-fns";

interface PredVsActualScatterProps {
  data: PredActualPoint[] | undefined;
  isLoading?: boolean;
}

export function PredVsActualScatter({ data, isLoading }: PredVsActualScatterProps) {
  // Calculate regression line and R²
  const stats = useMemo(() => {
    if (!data || data.length < 5) return null;
    
    const points = data.map((p) => ({
      x: p.predicted_move_bps,
      y: p.actual_move_bps,
    }));
    
    const n = points.length;
    const sumX = points.reduce((a, p) => a + p.x, 0);
    const sumY = points.reduce((a, p) => a + p.y, 0);
    const sumXY = points.reduce((a, p) => a + p.x * p.y, 0);
    const sumX2 = points.reduce((a, p) => a + p.x * p.x, 0);
    const sumY2 = points.reduce((a, p) => a + p.y * p.y, 0);
    
    const meanX = sumX / n;
    const meanY = sumY / n;
    
    const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    const intercept = meanY - slope * meanX;
    
    // R-squared
    const ssRes = points.reduce((a, p) => a + Math.pow(p.y - (slope * p.x + intercept), 2), 0);
    const ssTot = points.reduce((a, p) => a + Math.pow(p.y - meanY, 2), 0);
    const rSquared = ssTot > 0 ? 1 - ssRes / ssTot : 0;
    
    return { slope, intercept, rSquared };
  }, [data]);

  const chartData = data?.map((p) => ({
    predicted: p.predicted_move_bps,
    actual: p.actual_move_bps,
    confidence: p.confidence,
    symbol: p.symbol,
    direction: p.direction,
    ts: p.ts,
  })) ?? [];

  // Separate up and down predictions for coloring
  const upData = chartData.filter((p) => p.direction === "up");
  const downData = chartData.filter((p) => p.direction === "down");

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Predicted vs Actual</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[240px] animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Predicted vs Actual Move (bps)</CardTitle>
          {stats && (
            <span className="text-xs text-muted-foreground">
              R² = {stats.rSquared.toFixed(3)}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[240px]">
          {chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              No prediction data available yet
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="predicted"
                  type="number"
                  domain={[-20, 20]}
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  label={{
                    value: "Predicted (bps)",
                    position: "bottom",
                    offset: 0,
                    fontSize: 10,
                  }}
                />
                <YAxis
                  dataKey="actual"
                  type="number"
                  domain={[-20, 20]}
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  width={40}
                  label={{
                    value: "Actual (bps)",
                    angle: -90,
                    position: "insideLeft",
                    offset: 10,
                    fontSize: 10,
                  }}
                />
                <ZAxis dataKey="confidence" range={[20, 100]} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.[0]) return null;
                    const data = payload[0].payload;
                    return (
                      <div className="bg-popover border rounded-lg shadow-lg p-3 text-xs">
                        <p className="font-medium">{data.symbol}</p>
                        <p className="text-muted-foreground">
                          {format(new Date(data.ts), "HH:mm:ss")}
                        </p>
                        <p className="mt-1">
                          Predicted: {data.predicted.toFixed(2)} bps
                        </p>
                        <p>Actual: {data.actual.toFixed(2)} bps</p>
                        <p className="text-muted-foreground">
                          Conf: {(data.confidence * 100).toFixed(0)}%
                        </p>
                      </div>
                    );
                  }}
                />
                {/* Reference lines at 0 */}
                <ReferenceLine x={0} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.5} />
                <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.5} />
                {/* Perfect prediction line */}
                <ReferenceLine
                  segment={[
                    { x: -20, y: -20 },
                    { x: 20, y: 20 },
                  ]}
                  stroke="hsl(var(--muted-foreground))"
                  strokeDasharray="5 5"
                  strokeOpacity={0.3}
                />
                {/* Up predictions (green) */}
                <Scatter
                  name="Up"
                  data={upData}
                  fill="hsl(142 76% 36%)"
                  opacity={0.6}
                  isAnimationActive={false}
                />
                {/* Down predictions (red) */}
                <Scatter
                  name="Down"
                  data={downData}
                  fill="hsl(0 84% 60%)"
                  opacity={0.6}
                  isAnimationActive={false}
                />
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

