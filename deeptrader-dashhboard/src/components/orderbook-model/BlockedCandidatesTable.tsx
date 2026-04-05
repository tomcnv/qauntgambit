/**
 * BlockedCandidatesTable - Auditable table of blocked trade candidates
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
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";
import { ExternalLink } from "lucide-react";
import type { BlockedCandidateRow } from "../../types/orderbookModel";
import { format } from "date-fns";
import { Link } from "react-router-dom";

interface BlockedCandidatesTableProps {
  data: BlockedCandidateRow[] | undefined;
  isLoading?: boolean;
}

const reasonLabels: Record<string, string> = {
  direction_mismatch: "Direction",
  low_confidence: "Low Conf",
  low_move: "Small Move",
  neutral: "Neutral",
  stale_prediction: "Stale Pred",
  stale_orderbook: "Stale OB",
};

const reasonColors: Record<string, string> = {
  direction_mismatch: "bg-red-500/20 text-red-600 border-red-500/30",
  low_confidence: "bg-amber-500/20 text-amber-600 border-amber-500/30",
  low_move: "bg-blue-500/20 text-blue-600 border-blue-500/30",
  neutral: "bg-muted text-muted-foreground border-border",
  stale_prediction: "bg-orange-500/20 text-orange-600 border-orange-500/30",
  stale_orderbook: "bg-orange-500/20 text-orange-600 border-orange-500/30",
};

export function BlockedCandidatesTable({ data, isLoading }: BlockedCandidatesTableProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Blocked Candidates</CardTitle>
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

  const candidates = data ?? [];

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium">
          Blocked Candidates
          {candidates.length > 0 && (
            <Badge variant="outline" className="ml-2 text-[10px]">
              {candidates.length} blocked
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {candidates.length === 0 ? (
          <div className="p-6 text-center text-muted-foreground text-sm">
            No blocked candidates in this window
          </div>
        ) : (
          <div className="overflow-auto max-h-[300px]">
            <Table>
              <TableHeader className="sticky top-0 bg-card">
                <TableRow>
                  <TableHead className="text-xs">Time</TableHead>
                  <TableHead className="text-xs">Symbol</TableHead>
                  <TableHead className="text-xs text-center">Dir</TableHead>
                  <TableHead className="text-xs text-right">Conf</TableHead>
                  <TableHead className="text-xs text-right">Pred</TableHead>
                  <TableHead className="text-xs">Reason</TableHead>
                  <TableHead className="text-xs text-right">Actual</TableHead>
                  <TableHead className="text-xs w-[40px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {candidates.map((row, idx) => {
                  // Determine if blocking was correct
                  const wouldHaveBeenGood =
                    row.actual_move_bps_3s !== null &&
                    row.actual_move_bps_3s !== undefined &&
                    ((row.direction === "up" && row.actual_move_bps_3s > 0.5) ||
                      (row.direction === "down" && row.actual_move_bps_3s < -0.5));

                  return (
                    <TableRow key={idx}>
                      <TableCell className="font-mono text-xs">
                        {format(new Date(row.ts), "HH:mm:ss")}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{row.symbol}</TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[10px]",
                            row.direction === "up"
                              ? "text-emerald-600 border-emerald-500/30"
                              : "text-red-600 border-red-500/30"
                          )}
                        >
                          {row.direction === "up" ? "↑" : "↓"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {(row.confidence * 100).toFixed(0)}%
                      </TableCell>
                      <TableCell className="text-right text-xs font-mono">
                        {row.predicted_move_bps.toFixed(1)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[10px]",
                            reasonColors[row.block_reason] ?? ""
                          )}
                        >
                          {reasonLabels[row.block_reason] ?? row.block_reason}
                        </Badge>
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right text-xs font-mono",
                          row.actual_move_bps_3s === null || row.actual_move_bps_3s === undefined
                            ? "text-muted-foreground"
                            : wouldHaveBeenGood
                            ? "text-red-500" // Missed opportunity
                            : "text-emerald-600" // Good block
                        )}
                      >
                        {row.actual_move_bps_3s !== null && row.actual_move_bps_3s !== undefined
                          ? row.actual_move_bps_3s.toFixed(1)
                          : "—"}
                      </TableCell>
                      <TableCell>
                        {row.replay_url && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0"
                            asChild
                          >
                            <Link to={row.replay_url}>
                              <ExternalLink className="h-3 w-3" />
                            </Link>
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

