import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { ArrowUp, Shield, Target, TrendingUp, TrendingDown } from 'lucide-react';
import { useSlTpEvents } from '../lib/api/hooks';

interface SlTpEvent {
  timestamp: number;
  symbol: string;
  event_type: 'sl_adjustment' | 'tp_adjustment' | 'sl_placed' | 'tp_placed';
  old_value?: number;
  new_value?: number;
  value?: number;
  entry_price?: number;
  current_price?: number;
  side?: string;
  reason?: string;
}

const formatPrice = (price?: number) => {
  if (!price) return '—';
  return price >= 1000 ? price.toFixed(2) : price.toFixed(4);
};

const formatTime = (timestamp: number) => {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit' 
  });
};

const getEventIcon = (eventType: string) => {
  switch (eventType) {
    case 'sl_adjustment':
      return <Shield className="h-4 w-4 text-red-400" />;
    case 'tp_adjustment':
      return <Target className="h-4 w-4 text-green-400" />;
    case 'sl_placed':
      return <Shield className="h-4 w-4 text-yellow-400" />;
    case 'tp_placed':
      return <Target className="h-4 w-4 text-blue-400" />;
    default:
      return null;
  }
};

const getEventLabel = (eventType: string) => {
  switch (eventType) {
    case 'sl_adjustment':
      return 'SL Adjusted';
    case 'tp_adjustment':
      return 'TP Adjusted';
    case 'sl_placed':
      return 'SL Placed';
    case 'tp_placed':
      return 'TP Placed';
    default:
      return eventType;
  }
};

const getReasonBadge = (reason?: string) => {
  if (!reason) return null;
  const colors: Record<string, string> = {
    trailing_stop: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    adaptive: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    value_area_adaptive: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
    protective_order: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  };
  return (
    <Badge variant="outline" className={colors[reason] || ''}>
      {reason.replace(/_/g, ' ')}
    </Badge>
  );
};

export function SlTpEvents() {
  const { data, isLoading, error } = useSlTpEvents(20);

  const events = (data?.events || []) as SlTpEvent[];

  if (isLoading) {
    return (
      <Card className="border-white/5 bg-black/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">SL/TP Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading...</p>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-white/5 bg-black/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">SL/TP Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-red-400">Failed to load events</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-white/5 bg-black/30">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Shield className="h-4 w-4" />
            SL/TP Activity
          </CardTitle>
          {events.length > 0 && (
            <Badge variant="outline" className="text-xs">
              {events.length} events
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No SL/TP adjustments yet
          </p>
        ) : (
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {events.map((event, idx) => (
              <div
                key={`${event.timestamp}-${idx}`}
                className="flex items-center justify-between p-2 rounded-lg bg-white/5 border border-white/5"
              >
                <div className="flex items-center gap-3">
                  {getEventIcon(event.event_type)}
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{event.symbol}</span>
                      <Badge 
                        variant="outline" 
                        className={event.side === 'long' ? 'text-green-400 border-green-500/30' : 'text-red-400 border-red-500/30'}
                      >
                        {event.side === 'long' ? <TrendingUp className="h-3 w-3 mr-1" /> : <TrendingDown className="h-3 w-3 mr-1" />}
                        {event.side?.toUpperCase()}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground flex items-center gap-2">
                      <span>{getEventLabel(event.event_type)}</span>
                      {getReasonBadge(event.reason)}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  {event.old_value && event.new_value ? (
                    <div className="flex items-center gap-1 text-sm">
                      <span className="text-muted-foreground">${formatPrice(event.old_value)}</span>
                      <ArrowUp className={`h-3 w-3 ${event.new_value > event.old_value ? 'text-green-400' : 'text-red-400 rotate-180'}`} />
                      <span className={event.new_value > event.old_value ? 'text-green-400' : 'text-red-400'}>
                        ${formatPrice(event.new_value)}
                      </span>
                    </div>
                  ) : event.value ? (
                    <div className="text-sm font-medium">${formatPrice(event.value)}</div>
                  ) : null}
                  <div className="text-xs text-muted-foreground">
                    {formatTime(event.timestamp)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default SlTpEvents;
