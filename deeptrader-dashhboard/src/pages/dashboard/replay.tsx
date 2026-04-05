import { useState, useMemo } from "react";
import { RunBar } from "../../components/run-bar";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  useReplayData,
  useIncidents,
  useIncident,
  useCreateReplaySession,
} from "../../lib/api/hooks";
import { CandlestickChart, ExecutionMarker } from "../../components/dashboard/candlestick-chart";
import { ChartContainer } from "../../components/dashboard/chart-container";
import { cn } from "../../lib/utils";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Clock,
  AlertTriangle,
  TrendingDown,
  TrendingUp,
  FileText,
  Calendar,
  Loader2,
  FastForward,
  Rewind,
  RefreshCw,
} from "lucide-react";
import { CandlestickData } from "../../lib/api/types";
import toast from "react-hot-toast";

const formatUsd = (value?: number) =>
  value === undefined || Number.isNaN(value)
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);

const formatTime = (timestamp: string | number) => {
  const date = new Date(timestamp);
  return date.toLocaleString();
};

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case "critical":
      return "bg-red-500/10 text-red-300 border-red-500/20";
    case "high":
      return "bg-orange-500/10 text-orange-300 border-orange-500/20";
    case "medium":
      return "bg-yellow-500/10 text-yellow-300 border-yellow-500/20";
    case "low":
      return "bg-blue-500/10 text-blue-300 border-blue-500/20";
    default:
      return "bg-gray-500/10 text-gray-300 border-gray-500/20";
  }
};

const getStatusColor = (status: string) => {
  switch (status) {
    case "resolved":
      return "bg-emerald-500/10 text-emerald-300";
    case "investigating":
      return "bg-blue-500/10 text-blue-300";
    case "closed":
      return "bg-gray-500/10 text-gray-300";
    default:
      return "bg-yellow-500/10 text-yellow-300";
  }
};

export default function ReplayPage() {
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [startTime, setStartTime] = useState<string>("");
  const [endTime, setEndTime] = useState<string>("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTimeIndex, setCurrentTimeIndex] = useState<number>(0);
  const [playbackSpeed, setPlaybackSpeed] = useState<1 | 2 | 4>(1);

  // Fetch incidents
  const { data: incidentsData, isLoading: incidentsLoading } = useIncidents({
    limit: 50,
    status: "open",
  });

  // Fetch selected incident details
  const { data: incidentData } = useIncident(selectedIncidentId);

  // Fetch replay data
  const { data: replayData, isLoading: replayLoading } = useReplayData(
    selectedSymbol || null,
    startTime || null,
    endTime || null
  );

  const createSessionMutation = useCreateReplaySession();

  const incidents = incidentsData?.data || [];

  // Auto-populate from incident
  useMemo(() => {
    if (incidentData?.data && !selectedSymbol) {
      const incident = incidentData.data;
      setSelectedSymbol(incident.affected_symbols[0] || "");
      setStartTime(incident.start_time);
      setEndTime(incident.end_time);
    }
  }, [incidentData, selectedSymbol]);

  // Prepare candlestick data from snapshots
  const candlestickData = useMemo<CandlestickData[]>(() => {
    if (!replayData?.data?.snapshots) return [];

    return (replayData.data.snapshots || [])
      .flatMap((snapshot) => {
        const candles = snapshot.market_data?.candles || [];
        if (!candles || candles.length === 0) return [];
        return candles.map((candle) => ({
          time: Math.floor(new Date(snapshot.timestamp).getTime() / 1000),
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
          volume: candle.volume,
        }));
      })
      .sort((a, b) => a.time - b.time);
  }, [replayData]);

  // Prepare execution markers from traces
  const executionMarkers = useMemo<ExecutionMarker[]>(() => {
    if (!replayData?.data?.traces) return [];

    return (replayData.data.traces || [])
      .filter((trace: any) => trace?.final_decision && (trace.final_decision as any).action === "execute")
      .map((trace: any) => {
        const decision = trace.final_decision as any;
        return {
          time: Math.floor(new Date(trace.timestamp).getTime() / 1000),
          price: decision?.price || 0,
          side: (decision?.side || "buy").toLowerCase() as "buy" | "sell",
          size: decision?.size || 0,
        };
      });
  }, [replayData]);

  // Get timeline events (snapshots + traces)
  const timelineEvents = useMemo(() => {
    if (!replayData?.data) return [];

    const events: Array<{
      time: number;
      type: "snapshot" | "trace" | "trade" | "position";
      data: any;
    }> = [];

    (replayData.data.snapshots || []).forEach((snapshot) => {
      events.push({
        time: new Date(snapshot.timestamp).getTime(),
        type: "snapshot",
        data: snapshot,
      });
    });

    (replayData.data.traces || []).forEach((trace) => {
      events.push({
        time: new Date(trace.timestamp).getTime(),
        type: "trace",
        data: trace,
      });
    });

    (replayData.data.trades || []).forEach((trade) => {
      events.push({
        time: new Date(trade.entry_time).getTime(),
        type: "trade",
        data: trade,
      });
    });

    return events.sort((a, b) => a.time - b.time);
  }, [replayData]);

  const scrubTo = (direction: "back" | "forward") => {
    if (!timelineEvents.length) return;
    setCurrentTimeIndex((prev) => {
      if (direction === "back") return Math.max(0, prev - 1);
      return Math.min(timelineEvents.length - 1, prev + 1);
    });
  };

  const handleCreateSession = () => {
    if (!selectedSymbol || !startTime || !endTime) {
      toast.error("Please select symbol and time range");
      return;
    }

    createSessionMutation.mutate(
      {
        incidentId: selectedIncidentId || undefined,
        symbol: selectedSymbol,
        startTime,
        endTime,
        sessionName: `Replay: ${selectedSymbol} ${new Date(startTime).toLocaleDateString()}`,
      },
      {
        onSuccess: () => {
          toast.success("Replay session created");
        },
        onError: (error: any) => {
          toast.error(error.message || "Failed to create replay session");
        },
      }
    );
  };

  return (
    <>
      <RunBar variant="minimal" />
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Incident Replay</h1>
        <p className="text-sm text-muted-foreground">
          Time-machine investigation of trading incidents and decisions
        </p>
      </div>

      {/* Incident Selector */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Select Incident
          </CardTitle>
        </CardHeader>
        <CardContent>
          {incidentsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : incidents.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-sm text-muted-foreground">No incidents found</p>
              <p className="mt-2 text-xs text-muted-foreground">
                Incidents will appear here when significant events are detected
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {incidents.map((incident) => (
                <div
                  key={incident.id}
                  className={cn(
                    "rounded-lg border p-4 cursor-pointer transition hover:bg-white/5",
                    selectedIncidentId === incident.id
                      ? "border-white/20 bg-white/5"
                      : "border-white/5 bg-white/5"
                  )}
                  onClick={() => setSelectedIncidentId(incident.id)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-white">{incident.title}</h3>
                        <Badge className={getSeverityColor(incident.severity)}>
                          {incident.severity}
                        </Badge>
                        <Badge className={getStatusColor(incident.status)}>
                          {incident.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {incident.incident_type.replace(/_/g, " ")} • {incident.affected_symbols.join(", ")}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatTime(incident.start_time)} → {formatTime(incident.end_time)}
                      </p>
                      {incident.pnl_impact && (
                        <p className="mt-1 text-sm font-semibold text-red-400">
                          PnL Impact: {formatUsd(incident.pnl_impact)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Time Range & Symbol Selector */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Replay Configuration
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <Label htmlFor="symbol">Symbol</Label>
              <Input
                id="symbol"
                placeholder="BTC-USDT-SWAP"
                value={selectedSymbol}
                onChange={(e) => setSelectedSymbol(e.target.value)}
                disabled={!!incidentData?.data?.affected_symbols?.length}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="startTime">Start Time</Label>
              <Input
                id="startTime"
                type="datetime-local"
                value={startTime ? new Date(startTime).toISOString().slice(0, 16) : ""}
                onChange={(e) => setStartTime(new Date(e.target.value).toISOString())}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="endTime">End Time</Label>
              <Input
                id="endTime"
                type="datetime-local"
                value={endTime ? new Date(endTime).toISOString().slice(0, 16) : ""}
                onChange={(e) => setEndTime(new Date(e.target.value).toISOString())}
              />
            </div>
            <div className="flex items-end">
              <Button
                onClick={handleCreateSession}
                disabled={!selectedSymbol || !startTime || !endTime || createSessionMutation.isPending}
                className="w-full"
              >
                {createSessionMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="mr-2 h-4 w-4" />
                )}
                Create Session
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Replay Visualization */}
      {selectedSymbol && startTime && endTime && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
                Replay: {selectedSymbol}
              </CardTitle>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsPlaying(!isPlaying)}
                >
                  {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => scrubTo("back")}>
                  <SkipBack className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => scrubTo("forward")}>
                  <SkipForward className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setPlaybackSpeed((s) => (s === 4 ? 1 : (s * 2) as 1 | 2 | 4))}>
                  {playbackSpeed}x
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setCurrentTimeIndex(0)}>
                  <Rewind className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setCurrentTimeIndex(timelineEvents.length ? timelineEvents.length - 1 : 0)}>
                  <FastForward className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {replayLoading ? (
              <div className="flex h-96 items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : !replayData?.data ? (
              <div className="flex h-96 items-center justify-center">
                <p className="text-sm text-muted-foreground">No replay data available</p>
              </div>
            ) : (
              <div className="space-y-6">
                <ChartContainer
                  title={`${selectedSymbol} Price Chart`}
                  description="Candlestick chart with decision markers"
                  height="h-96"
                >
                  {candlestickData.length > 0 ? (
                    <CandlestickChart
                      data={candlestickData}
                      executionMarkers={executionMarkers}
                      height={384}
                    />
                  ) : (
                    <div className="flex h-96 items-center justify-center">
                      <p className="text-sm text-muted-foreground">No market data available</p>
                    </div>
                  )}
                </ChartContainer>

                {/* Timeline Events */}
                {timelineEvents.length > 0 ? (
                  <div>
                    <h3 className="mb-4 text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                      Timeline Events ({timelineEvents.length})
                    </h3>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
              {timelineEvents.slice(0, 50).map((event, idx) => (
                <div
                  key={`${event.time}-${idx}`}
                  className={cn(
                    "rounded-lg border border-white/5 bg-white/5 p-3",
                    idx === currentTimeIndex && "border-primary/50 bg-primary/5"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs">
                        {event.type}
                      </Badge>
                      <span className="text-sm text-white">
                        {formatTime(event.time)}
                      </span>
                    </div>
                    {event.type === "trace" && (
                      <Badge
                        className={
                          event.data.decision_outcome === "approved"
                            ? "bg-emerald-500/10 text-emerald-300"
                            : "bg-red-500/10 text-red-300"
                        }
                      >
                        {event.data.decision_outcome}
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">No timeline events for this window.</div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
      </div>
    </>
  );
}





