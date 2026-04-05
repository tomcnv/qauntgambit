import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { AlertTriangle, X, RefreshCw } from 'lucide-react';
import { useOrphanedPositions, useClosePosition, useCloseAllOrphanedPositions } from '../lib/api/hooks';

interface Position {
  symbol: string;
  side: 'LONG' | 'SHORT';
  quantity: number;
  entryPrice: number;
  markPrice: number;
  unrealizedPnl: number;
  leverage: number;
  liquidationPrice?: number;
  stopLoss?: number | null;
  takeProfit?: number | null;
}

export function OrphanedPositions() {
  const [closingSymbol, setClosingSymbol] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useOrphanedPositions();
  const closePositionMutation = useClosePosition();
  const closeAllMutation = useCloseAllOrphanedPositions();

  const orphanedPositions = (data?.orphanedPositions || []) as Position[];
  const hasOrphans = orphanedPositions.length > 0;

  if (!hasOrphans && !isLoading) {
    return null; // Don't show anything if no orphaned positions
  }

  const totalUnrealizedPnl = orphanedPositions.reduce((sum, p) => sum + p.unrealizedPnl, 0);

  const handleClosePosition = (position: Position) => {
    setClosingSymbol(position.symbol);
    closePositionMutation.mutate(
      {
        symbol: position.symbol,
        side: position.side === 'LONG' ? 'SELL' : 'BUY',
        quantity: position.quantity,
      },
      {
        onSettled: () => setClosingSymbol(null),
      }
    );
  };

  return (
    <Card className={hasOrphans ? 'border-yellow-500 bg-yellow-500/5' : ''}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            {hasOrphans && <AlertTriangle className="h-5 w-5 text-yellow-500" />}
            Orphaned Positions
            {hasOrphans && (
              <Badge variant="outline" className="ml-2 text-yellow-600 border-yellow-500">
                {orphanedPositions.length}
              </Badge>
            )}
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4" />
            </Button>
            {hasOrphans && (
              <Button
                variant="default"
                size="sm"
                className="bg-red-600 hover:bg-red-700 border-red-600"
                onClick={() => closeAllMutation.mutate()}
                disabled={closeAllMutation.isPending}
              >
                {closeAllMutation.isPending ? 'Closing...' : 'Close All'}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="text-sm text-muted-foreground">Loading positions...</div>
        ) : error ? (
          <div className="text-sm text-red-500">Failed to load positions</div>
        ) : !hasOrphans ? (
          <div className="text-sm text-muted-foreground">No orphaned positions</div>
        ) : (
          <div className="space-y-3">
            <div className="text-sm text-muted-foreground mb-2">
              These positions exist on the exchange but aren't being tracked by the bot.
              Total unrealized P&L:{' '}
              <span className={totalUnrealizedPnl >= 0 ? 'text-green-500' : 'text-red-500'}>
                ${totalUnrealizedPnl.toFixed(2)}
              </span>
            </div>
            <div className="space-y-3">
              {orphanedPositions.map((position) => (
                <div
                  key={position.symbol}
                  className="p-4 rounded-lg bg-muted/50 border border-muted"
                >
                  {/* Header row */}
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <Badge 
                        variant="default"
                        className={position.side === 'LONG' ? 'bg-green-600 border-green-500' : 'bg-red-600 border-red-500'}
                      >
                        {position.side === 'LONG' ? '↑ LONG' : '↓ SHORT'}
                      </Badge>
                      <span className="font-semibold text-lg">{position.symbol}</span>
                      <span className="text-xs text-muted-foreground">{position.leverage}x</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div
                        className={`font-bold text-lg ${
                          position.unrealizedPnl >= 0 ? 'text-green-500' : 'text-red-500'
                        }`}
                      >
                        {position.unrealizedPnl >= 0 ? '+' : ''}${position.unrealizedPnl.toFixed(2)}
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleClosePosition(position)}
                        disabled={closingSymbol === position.symbol}
                      >
                        {closingSymbol === position.symbol ? (
                          <RefreshCw className="h-4 w-4 animate-spin mr-1" />
                        ) : (
                          <X className="h-4 w-4 mr-1" />
                        )}
                        Close
                      </Button>
                    </div>
                  </div>

                  {/* Details grid */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <div>
                      <div className="text-muted-foreground text-xs">Size</div>
                      <div className="font-medium">{position.quantity}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs">Entry</div>
                      <div className="font-medium">${position.entryPrice.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs">Mark Price</div>
                      <div className="font-medium">${position.markPrice.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs">Liquidation</div>
                      <div className="font-medium text-orange-500">
                        {position.liquidationPrice ? `$${position.liquidationPrice.toFixed(2)}` : '—'}
                      </div>
                    </div>
                  </div>

                  {/* SL/TP row */}
                  <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-muted text-sm">
                    <div className="flex items-center gap-2">
                      <span className="text-red-500 font-medium">SL:</span>
                      {position.stopLoss ? (
                        <span className="text-red-400">${position.stopLoss.toFixed(2)}</span>
                      ) : (
                        <span className="text-muted-foreground italic">Not set</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-green-500 font-medium">TP:</span>
                      {position.takeProfit ? (
                        <span className="text-green-400">${position.takeProfit.toFixed(2)}</span>
                      ) : (
                        <span className="text-muted-foreground italic">Not set</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default OrphanedPositions;
