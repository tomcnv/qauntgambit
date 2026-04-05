/**
 * TradesTable - Elegant data table with integrated header, filters, pagination
 * Matches the "Recent Orders" card design pattern
 */

import { useState, useMemo } from 'react';
import {
  ColumnDef,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import { cn } from '../../lib/utils';
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  MoreHorizontal,
  Eye,
  RefreshCw,
  Download,
  Tag,
  AlertTriangle,
  Loader2,
  Columns3,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { QuantTrade } from './types';
import { TradeCopilotIcon } from '@/components/copilot/TradeCopilotIcon';
import { QuantTrade as CopilotQuantTrade } from '@/store/copilot-store';

interface TradesTableProps {
  trades: QuantTrade[];
  onSelectTrade: (trade: QuantTrade) => void;
  onReplayTrade?: (trade: QuantTrade) => void;
  onExportTrade?: (trade: QuantTrade) => void;
  onTagTrade?: (trade: QuantTrade) => void;
  selectedTradeId?: string | null;
  isLoading?: boolean;
  isFetching?: boolean;
  // Pagination
  total?: number;
  offset?: number;
  limit?: number;
  onOffsetChange?: (offset: number) => void;
}

const formatUsd = (value?: number, showSign = false) => {
  if (value === undefined || Number.isNaN(value)) return '—';
  const formatted = new Intl.NumberFormat('en-US', { 
    style: 'currency', 
    currency: 'USD', 
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  if (showSign) {
    return value >= 0 ? `+${formatted}` : `-${formatted}`;
  }
  return formatted;
};

const formatPrice = (value?: number) => {
  if (value === undefined || Number.isNaN(value)) return '—';
  // For crypto prices, show more decimals for small values
  const decimals = value < 1 ? 6 : value < 100 ? 4 : 2;
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
};

const formatDateTime = (timestamp?: number) => {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  const month = date.toLocaleDateString('en-US', { month: 'short' });
  const day = date.getDate();
  const time = date.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit',
    hour12: false 
  });
  return `${month} ${day}, ${time}`;
};

const formatQuantity = (value?: number) => {
  if (value === undefined || Number.isNaN(value)) return '—';
  if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (value >= 1) return value.toFixed(4);
  return value.toFixed(6);
};

/** Map trade-history QuantTrade to copilot store QuantTrade shape */
function toCopilotTrade(trade: QuantTrade): CopilotQuantTrade {
  return {
    id: trade.id,
    symbol: trade.symbol,
    side: trade.side,
    entry_price: trade.entryPrice,
    exit_price: trade.exitPrice,
    pnl: trade.netPnl,
    holdingDuration: trade.holdTimeSeconds * 1000,
    decisionTrace: trade.decisionTraceId,
    size: trade.quantity,
    timestamp: trade.timestamp,
  };
}

// Sortable header component
function SortableHeader({ column, children, className }: { column: any; children: React.ReactNode; className?: string }) {
  const sorted = column.getIsSorted();
  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn("-ml-3 h-8 hover:bg-transparent", className)}
      onClick={() => column.toggleSorting(sorted === 'asc')}
    >
      {children}
      {sorted === 'asc' ? (
        <ArrowUp className="ml-1.5 h-3 w-3" />
      ) : sorted === 'desc' ? (
        <ArrowDown className="ml-1.5 h-3 w-3" />
      ) : (
        <ArrowUpDown className="ml-1.5 h-3 w-3 opacity-40" />
      )}
    </Button>
  );
}

export function TradesTable({
  trades,
  onSelectTrade,
  onReplayTrade,
  onExportTrade,
  onTagTrade,
  selectedTradeId,
  isLoading,
  isFetching,
  total = 0,
  offset = 0,
  limit = 100,
  onOffsetChange,
}: TradesTableProps) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'timestamp', desc: true }]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({
    // Hide some columns by default
    side: true,
    fees: false,
    latencyMs: false,
    slippageBps: false,
    rMultiple: false,
    maeBps: false,
    mfeBps: false,
  });

  // Define columns with TanStack Table
  const columns: ColumnDef<QuantTrade>[] = useMemo(() => [
    {
      id: 'timestamp',
      accessorKey: 'timestamp',
      header: ({ column }) => <SortableHeader column={column}>Time</SortableHeader>,
      cell: ({ row }) => (
        <span className="font-mono text-xs text-muted-foreground whitespace-nowrap">
          {formatDateTime(row.original.timestamp)}
        </span>
      ),
      size: 140,
    },
    {
      id: 'symbol',
      accessorKey: 'symbol',
      header: ({ column }) => <SortableHeader column={column}>Symbol</SortableHeader>,
      cell: ({ row }) => (
        <span className="font-medium whitespace-nowrap">
          {row.original.symbol}
        </span>
      ),
      size: 130,
    },
    {
      id: 'botName',
      accessorKey: 'botId',
      header: () => <span>Bot</span>,
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground truncate max-w-[100px] block" title={row.original.botId || ''}>
          {row.original.botName || row.original.botId?.slice(0, 8) || '—'}
        </span>
      ),
      size: 90,
    },
    {
      id: 'side',
      accessorKey: 'side',
      header: ({ column }) => <SortableHeader column={column}>Side</SortableHeader>,
      cell: ({ row }) => {
        const side = row.original.side;
        const isLong = side === 'long' || side === 'buy';
        return (
          <Badge 
            variant="outline"
            className={cn(
              "text-[10px] px-2 py-0.5 font-medium uppercase rounded-full",
              isLong 
                ? "border-emerald-500/50 text-emerald-600 bg-emerald-500/10" 
                : "border-red-500/50 text-red-600 bg-red-500/10"
            )}
          >
            {isLong ? 'LONG' : 'SHORT'}
          </Badge>
        );
      },
      size: 75,
    },
    {
      id: 'liquidity',
      accessorKey: 'liquidity',
      header: ({ column }) => <SortableHeader column={column}>Liquidity</SortableHeader>,
      cell: ({ row }) => {
        const liquidity = row.original.liquidity;
        const makerPercent = row.original.makerPercent;
        if (liquidity === 'maker') {
          return (
            <Badge variant="outline" className="text-[10px] px-2 py-0.5 rounded-full border-emerald-500/50 text-emerald-600 bg-emerald-500/10">
              MAKER
            </Badge>
          );
        }
        if (liquidity === 'taker') {
          return (
            <Badge variant="outline" className="text-[10px] px-2 py-0.5 rounded-full border-amber-500/50 text-amber-600 bg-amber-500/10">
              TAKER
            </Badge>
          );
        }
        if (typeof makerPercent === 'number') {
          return (
            <span className="font-mono text-xs text-muted-foreground whitespace-nowrap">
              MIXED {(makerPercent * 100).toFixed(0)}%
            </span>
          );
        }
        return <span className="text-muted-foreground">—</span>;
      },
      size: 92,
    },
    {
      id: 'quantity',
      accessorKey: 'quantity',
      header: () => <span className="text-right block">Size</span>,
      cell: ({ row }) => (
        <span className="font-mono text-xs text-right block whitespace-nowrap">
          {formatQuantity(row.original.quantity)}
        </span>
      ),
      size: 90,
    },
    {
      id: 'entryPrice',
      accessorKey: 'entryPrice',
      header: () => <span className="text-right block">Entry</span>,
      cell: ({ row }) => (
        <span className="font-mono text-xs text-right block whitespace-nowrap">
          {formatPrice(row.original.entryPrice)}
        </span>
      ),
      size: 110,
    },
    {
      id: 'exitPrice',
      accessorKey: 'exitPrice',
      header: () => <span className="text-right block">Exit</span>,
      cell: ({ row }) => (
        <span className="font-mono text-xs text-right block whitespace-nowrap">
          {row.original.exitPrice ? formatPrice(row.original.exitPrice) : '—'}
        </span>
      ),
      size: 110,
    },
    {
      id: 'netPnl',
      accessorKey: 'netPnl',
      header: ({ column }) => (
        <div className="text-right">
          <SortableHeader column={column} className="justify-end">P&L</SortableHeader>
        </div>
      ),
      cell: ({ row }) => {
        const pnl = row.original.netPnl;
        if (pnl === undefined) return <span className="text-right block text-muted-foreground">—</span>;
        return (
          <span className={cn(
            "font-mono text-xs font-medium text-right block whitespace-nowrap",
            pnl >= 0 ? "text-emerald-600" : "text-red-600"
          )}>
            {formatUsd(pnl, true)}
          </span>
        );
      },
      size: 100,
    },
    {
      id: 'fees',
      accessorKey: 'fees',
      header: () => <span className="text-right block">Fees</span>,
      cell: ({ row }) => (
        <span className="font-mono text-xs text-muted-foreground text-right block whitespace-nowrap">
          {row.original.fees ? `-${formatUsd(Math.abs(row.original.fees))}` : '—'}
        </span>
      ),
      size: 80,
    },
    {
      id: 'slippageBps',
      accessorKey: 'slippageBps',
      header: () => <span className="text-right block">Slip</span>,
      cell: ({ row }) => {
        const slip = row.original.slippageBps;
        return (
          <span className={cn(
            "font-mono text-xs text-right block whitespace-nowrap",
            slip && slip > 3 ? "text-amber-500" : "text-muted-foreground"
          )}>
            {slip !== undefined ? `${slip.toFixed(1)}bp` : '—'}
          </span>
        );
      },
      size: 65,
    },
    {
      id: 'latencyMs',
      accessorKey: 'latencyMs',
      header: () => <span className="text-right block">Latency</span>,
      cell: ({ row }) => {
        const lat = row.original.latencyMs;
        return (
          <span className={cn(
            "font-mono text-xs text-right block whitespace-nowrap",
            lat && lat > 100 ? "text-amber-500" : "text-muted-foreground"
          )}>
            {lat !== undefined ? `${lat}ms` : '—'}
          </span>
        );
      },
      size: 70,
    },
    {
      id: 'rMultiple',
      accessorKey: 'rMultiple',
      header: () => <span className="text-right block">R</span>,
      cell: ({ row }) => {
        const r = row.original.rMultiple;
        if (r === undefined) return <span className="text-right block text-muted-foreground">—</span>;
        return (
          <span className={cn(
            "font-mono text-xs text-right block whitespace-nowrap",
            r >= 0 ? "text-emerald-600" : "text-red-600"
          )}>
            {r >= 0 ? '+' : ''}{r.toFixed(1)}R
          </span>
        );
      },
      size: 60,
    },
    {
      id: 'maeBps',
      accessorKey: 'maeBps',
      header: () => <span className="text-right block">MAE</span>,
      cell: ({ row }) => {
        const mae = row.original.maeBps;
        return (
          <span className="font-mono text-xs text-red-500/70 text-right block whitespace-nowrap">
            {mae !== undefined ? `${mae.toFixed(0)}bp` : '—'}
          </span>
        );
      },
      size: 60,
    },
    {
      id: 'mfeBps',
      accessorKey: 'mfeBps',
      header: () => <span className="text-right block">MFE</span>,
      cell: ({ row }) => {
        const mfe = row.original.mfeBps;
        return (
          <span className="font-mono text-xs text-emerald-500/70 text-right block whitespace-nowrap">
            {mfe !== undefined ? `${mfe.toFixed(0)}bp` : '—'}
          </span>
        );
      },
      size: 60,
    },
    {
      id: 'exitReason',
      accessorKey: 'exitReason',
      header: 'Exit',
      cell: ({ row }) => {
        const reason = row.original.exitReason;
        if (!reason) return <span className="text-muted-foreground">—</span>;
        
        const exitColors: Record<string, string> = {
          stop_loss: 'border-red-500/50 text-red-600 bg-red-500/10',
          take_profit: 'border-emerald-500/50 text-emerald-600 bg-emerald-500/10',
          signal_exit: 'border-blue-500/50 text-blue-600 bg-blue-500/10',
          time_exit: 'border-amber-500/50 text-amber-600 bg-amber-500/10',
          manual: 'border-purple-500/50 text-purple-600 bg-purple-500/10',
        };
        
        return (
          <Badge 
            variant="outline" 
            className={cn("text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap", exitColors[reason])}
          >
            {reason.replace('_', ' ')}
          </Badge>
        );
      },
      size: 90,
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          <Button 
            variant="outline" 
            size="sm" 
            className="h-7 px-2.5 text-xs"
            onClick={(e) => { e.stopPropagation(); onSelectTrade(row.original); }}
          >
            View
          </Button>
          {onReplayTrade && (
            <Button 
              variant="ghost" 
              size="sm" 
              className="h-7 px-2.5 text-xs"
              onClick={(e) => { e.stopPropagation(); onReplayTrade(row.original); }}
            >
              Replay
            </Button>
          )}
          <span onClick={(e) => e.stopPropagation()}>
            <TradeCopilotIcon trade={toCopilotTrade(row.original)} />
          </span>
        </div>
      ),
      size: 140,
    },
  ], [onSelectTrade, onReplayTrade]);

  const table = useReactTable({
    data: trades,
    columns,
    state: {
      sorting,
      columnVisibility,
    },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const hasMore = offset + limit < total;
  const canGoPrev = offset > 0;

  // Column display names for the dropdown
  const columnLabels: Record<string, string> = {
    timestamp: 'Time',
    symbol: 'Symbol',
    side: 'Side',
    liquidity: 'Liquidity',
    quantity: 'Size',
    entryPrice: 'Entry Price',
    exitPrice: 'Exit Price',
    netPnl: 'P&L',
    fees: 'Fees',
    slippageBps: 'Slippage',
    latencyMs: 'Latency',
    rMultiple: 'R Multiple',
    maeBps: 'MAE',
    mfeBps: 'MFE',
    exitReason: 'Exit Reason',
    actions: 'Actions',
  };

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      {/* Scrollable container */}
      <div className="overflow-auto" style={{ maxHeight: 'calc(100vh - 400px)' }}>
        <table className="w-full text-sm">
          {/* Sticky Header with title row + column headers */}
          <thead className="sticky top-0 z-20 bg-card">
            {/* Title row */}
            <tr className="border-b">
              <th colSpan={table.getVisibleLeafColumns().length} className="p-0">
                <div className="flex items-center justify-between px-4 py-3">
                  <div>
                    <h3 className="font-semibold text-foreground text-left">Trade History</h3>
                    <p className="text-xs text-muted-foreground text-left font-normal">
                      Click trades to view detailed analysis
                    </p>
                  </div>
                  
                  <div className="flex items-center gap-3">
                    {/* Trade count */}
                    <span className="text-xs text-muted-foreground uppercase tracking-wide">
                      {total.toLocaleString()} {total === 1 ? 'trade' : 'trades'}
                      {isFetching && <Loader2 className="inline ml-2 h-3 w-3 animate-spin" />}
                    </span>
                    
                    {/* Column visibility dropdown */}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-8 gap-2">
                          <Columns3 className="h-3.5 w-3.5" />
                          Columns
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48">
                        <DropdownMenuLabel>Toggle columns</DropdownMenuLabel>
                        <DropdownMenuSeparator />
                        {table.getAllLeafColumns()
                          .filter(col => col.id !== 'actions')
                          .map((column) => (
                            <DropdownMenuCheckboxItem
                              key={column.id}
                              checked={column.getIsVisible()}
                              onCheckedChange={(value) => column.toggleVisibility(!!value)}
                            >
                              {columnLabels[column.id] || column.id}
                            </DropdownMenuCheckboxItem>
                          ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                    
                    {/* Pagination */}
                    {onOffsetChange && (
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-muted-foreground mr-2">
                          {offset + 1}–{Math.min(offset + limit, total)} of {total}
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 w-8 p-0"
                          disabled={!canGoPrev}
                          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 w-8 p-0"
                          disabled={!hasMore}
                          onClick={() => onOffsetChange(offset + limit)}
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              </th>
            </tr>
            
            {/* Column headers */}
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="bg-muted/50">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground border-y border-border"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          
          {/* Table body */}
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={table.getVisibleLeafColumns().length} className="h-64">
                  <div className="flex flex-col items-center justify-center text-muted-foreground">
                    <AlertTriangle className="h-10 w-10 mb-3 opacity-30" />
                    <p className="text-sm">No trades match the current filters</p>
                  </div>
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => {
                const isSelected = row.original.id === selectedTradeId;
                return (
                  <tr
                    key={row.id}
                    data-state={isSelected ? 'selected' : undefined}
                    className={cn(
                      "border-b border-border/50 cursor-pointer transition-colors hover:bg-muted/30",
                      isSelected && "bg-primary/5"
                    )}
                    onClick={() => onSelectTrade(row.original)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td
                        key={cell.id}
                        style={{ width: cell.column.getSize() }}
                        className="px-4 py-3"
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default TradesTable;
