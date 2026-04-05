/**
 * ReliabilityCurveChart - Confidence calibration chart
 * 
 * Shows how well-calibrated the model's confidence scores are.
 * Perfect calibration = diagonal line.
 */

import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { ReliabilityBin } from "../../types/orderbookModel";

interface ReliabilityCurveChartProps {
  data: ReliabilityBin[] | undefined;
  isLoading?: boolean;
}

export function ReliabilityCurveChart({ data, isLoading }: ReliabilityCurveChartProps) {
  const chartData = data?.map((bin) => ({
    bin: `${(bin.bin_start * 100).toFixed(0)}-${(bin.bin_end * 100).toFixed(0)}`,
    binMid: (bin.bin_start + bin.bin_end) / 2,
    observed: bin.observed_accuracy * 100,
    perfect: ((bin.bin_start + bin.bin_end) / 2) * 100,
    n: bin.n,
  })) ?? [];

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Confidence Calibration</CardTitle>
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
        <CardTitle className="text-sm font-medium">
          Confidence Calibration
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            (closer to diagonal = better calibrated)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[240px]">
          {chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              No calibration data available yet
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="bin"
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  label={{
                    value: "Confidence Bucket (%)",
                    position: "bottom",
                    offset: 0,
                    fontSize: 10,
                  }}
                />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  className="text-xs"
                  tick={{ fontSize: 10 }}
                  width={40}
                  label={{
                    value: "Observed Accuracy",
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
                        <p className="font-medium">Confidence: {data.bin}%</p>
                        <p className="text-primary mt-1">
                          Observed: {data.observed.toFixed(1)}%
                        </p>
                        <p className="text-muted-foreground">
                          Perfect: {data.perfect.toFixed(1)}%
                        </p>
                        <p className="text-muted-foreground">
                          Sample size: {data.n}
                        </p>
                      </div>
                    );
                  }}
                />
                {/* Perfect calibration line */}
                <ReferenceLine
                  segment={[
                    { x: "50-60", y: 55 },
                    { x: "90-100", y: 95 },
                  ]}
                  stroke="hsl(var(--muted-foreground))"
                  strokeDasharray="5 5"
                  strokeOpacity={0.5}
                />
                {/* Sample size bars */}
                <Bar
                  dataKey="n"
                  fill="hsl(var(--muted))"
                  opacity={0.3}
                  yAxisId="right"
                  isAnimationActive={false}
                />
                {/* Observed accuracy line */}
                <Line
                  type="monotone"
                  dataKey="observed"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  dot={{ fill: "hsl(var(--primary))", strokeWidth: 0, r: 4 }}
                  isAnimationActive={false}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tickFormatter={(v) => `n=${v}`}
                  className="text-xs"
                  tick={{ fontSize: 9 }}
                  width={35}
                  hide
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

