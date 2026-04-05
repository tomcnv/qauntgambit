/**
 * SymbolScoreboardTable - Per-symbol performance breakdown
 */

import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui/table";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import type { SymbolScoreboardRow } from "../../types/orderbookModel";

interface SymbolScoreboardTableProps {
  data: SymbolScoreboardRow[] | undefined;
  isLoading?: boolean;
  onSymbolClick?: (symbol: string) => void;
}

export function SymbolScoreboardTable({
  data,
  isLoading,
  onSymbolClick,
}: SymbolScoreboardTableProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Symbol Scoreboard</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-8 animate-pulse bg-muted rounded" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  const symbols = data ?? [];

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium">
          Symbol Scoreboard
          {symbols.length > 0 && (
            <Badge variant="outline" className="ml-2 text-[10px]">
              {symbols.length} symbols
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {symbols.length === 0 ? (
          <div className="p-6 text-center text-muted-foreground text-sm">
            No symbol data available yet
          </div>
        ) : (
          <div className="overflow-auto max-h-[300px]">
            <Table>
              <TableHeader className="sticky top-0 bg-card">
                <TableRow>
                  <TableHead className="text-xs">Symbol</TableHead>
                  <TableHead className="text-xs text-right">Preds</TableHead>
                  <TableHead className="text-xs text-right">Valid%</TableHead>
                  <TableHead className="text-xs text-right">Acc%</TableHead>
                  <TableHead className="text-xs text-right">Roll%</TableHead>
                  <TableHead className="text-xs text-center">Bias</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {symbols.map((row) => (
                  <TableRow
                    key={row.symbol}
                    className={cn(
                      "cursor-pointer hover:bg-muted/50",
                      onSymbolClick && "cursor-pointer"
                    )}
                    onClick={() => onSymbolClick?.(row.symbol)}
                  >
                    <TableCell className="font-mono text-xs">
                      {row.symbol}
                    </TableCell>
                    <TableCell className="text-right text-xs">
                      {row.directional_made}
                    </TableCell>
                    <TableCell className="text-right text-xs">
                      <span
                        className={cn(
                          row.validation_rate_pct >= 90
                            ? "text-emerald-600"
                            : row.validation_rate_pct < 70
                            ? "text-red-500"
                            : ""
                        )}
                      >
                        {row.validation_rate_pct.toFixed(0)}%
                      </span>
                    </TableCell>
                    <TableCell className="text-right text-xs">
                      <span
                        className={cn(
                          row.accuracy_pct >= 60
                            ? "text-emerald-600"
                            : row.accuracy_pct < 50
                            ? "text-red-500"
                            : ""
                        )}
                      >
                        {row.accuracy_pct.toFixed(1)}%
                      </span>
                    </TableCell>
                    <TableCell className="text-right text-xs">
                      <span
                        className={cn(
                          row.rolling_accuracy_pct >= 60
                            ? "text-emerald-600"
                            : row.rolling_accuracy_pct < 50
                            ? "text-red-500"
                            : ""
                        )}
                      >
                        {row.rolling_accuracy_pct.toFixed(1)}%
                      </span>
                    </TableCell>
                    <TableCell className="text-center">
                      <div className="flex items-center justify-center gap-0.5">
                        <span
                          className="text-[10px]"
                          style={{
                            width: `${Math.max(8, row.bias.up_pct / 3)}px`,
                            height: "8px",
                            backgroundColor: "hsl(var(--emerald-500))",
                            display: "inline-block",
                            borderRadius: "2px 0 0 2px",
                          }}
                          title={`Up: ${row.bias.up_pct.toFixed(0)}%`}
                        />
                        <span
                          className="text-[10px]"
                          style={{
                            width: `${Math.max(8, row.bias.down_pct / 3)}px`,
                            height: "8px",
                            backgroundColor: "hsl(var(--red-500))",
                            display: "inline-block",
                            borderRadius: "0 2px 2px 0",
                          }}
                          title={`Down: ${row.bias.down_pct.toFixed(0)}%`}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

