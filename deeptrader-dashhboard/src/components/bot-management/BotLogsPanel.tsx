/**
 * Bot Logs Panel Component
 * 
 * Displays error logs and event history for a bot instance.
 * Features:
 * - Filterable by log level (error, warn, info)
 * - Filterable by category (lifecycle, trade, connection, etc.)
 * - Real-time stats (24h error count)
 * - Clear error state action
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import toast from "react-hot-toast";
import {
  AlertTriangle,
  AlertCircle,
  Info,
  Bug,
  Skull,
  RefreshCw,
  Filter,
  XCircle,
  Activity,
  Zap,
  Link2,
  Settings,
  Server,
  CheckCircle,
} from "lucide-react";

import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { ScrollArea } from "../ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "../ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { api } from "../../lib/api/client";

interface BotLog {
  id: string;
  bot_instance_id: string;
  bot_exchange_config_id: string | null;
  user_id: string;
  level: "debug" | "info" | "warn" | "error" | "fatal";
  category: "lifecycle" | "trade" | "signal" | "risk" | "connection" | "config" | "system";
  message: string;
  details: Record<string, unknown>;
  error_code: string | null;
  error_type: string | null;
  stack_trace: string | null;
  symbol: string | null;
  source: string | null;
  created_at: string;
  environment?: string;
}

interface LogStats {
  debug: number;
  info: number;
  warn: number;
  error: number;
  fatal: number;
  total: number;
}

interface BotLogsPanelProps {
  botId: string;
  botName: string;
  configId?: string;
  onClearErrors?: () => void;
}

const LEVEL_ICONS: Record<string, React.ReactNode> = {
  debug: <Bug className="h-4 w-4 text-slate-400" />,
  info: <Info className="h-4 w-4 text-blue-400" />,
  warn: <AlertTriangle className="h-4 w-4 text-amber-400" />,
  error: <AlertCircle className="h-4 w-4 text-red-400" />,
  fatal: <Skull className="h-4 w-4 text-red-600" />,
};

const LEVEL_COLORS: Record<string, string> = {
  debug: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  info: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  warn: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  error: "bg-red-500/20 text-red-300 border-red-500/30",
  fatal: "bg-red-700/30 text-red-200 border-red-600/40",
};

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  lifecycle: <Activity className="h-3 w-3" />,
  trade: <Zap className="h-3 w-3" />,
  signal: <Activity className="h-3 w-3" />,
  risk: <AlertTriangle className="h-3 w-3" />,
  connection: <Link2 className="h-3 w-3" />,
  config: <Settings className="h-3 w-3" />,
  system: <Server className="h-3 w-3" />,
};

export default function BotLogsPanel({ botId, botName, configId, onClearErrors }: BotLogsPanelProps) {
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const queryClient = useQueryClient();

  // Fetch logs
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["bot-logs", botId, levelFilter, categoryFilter],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (levelFilter !== "all") {
        params.set("level", levelFilter === "errors" ? "error,fatal" : levelFilter);
      }
      if (categoryFilter !== "all") {
        params.set("category", categoryFilter);
      }
      params.set("limit", "100");
      
      const response = await api.get(`/bot-instances/${botId}/logs?${params}`);
      return response.data as { logs: BotLog[]; stats: LogStats };
    },
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Clear errors mutation
  const clearErrorsMutation = useMutation({
    mutationFn: async () => {
      if (!configId) throw new Error("No config ID provided");
      await api.post(`/bot-instances/${botId}/configs/${configId}/clear-errors`);
    },
    onSuccess: () => {
      toast.success("Error state cleared");
      queryClient.invalidateQueries({ queryKey: ["bot-logs", botId] });
      queryClient.invalidateQueries({ queryKey: ["bot-instances"] });
      onClearErrors?.();
    },
    onError: (error: Error) => {
      toast.error(`Failed to clear errors: ${error.message}`);
    },
  });

  const logs = data?.logs || [];
  const stats = data?.stats || { debug: 0, info: 0, warn: 0, error: 0, fatal: 0, total: 0 };
  const errorCount = stats.error + stats.fatal;

  return (
    <div className="space-y-4">
      {/* Stats Header */}
      <div className="grid grid-cols-5 gap-2">
        <StatTile label="Total" value={stats.total} color="text-slate-300" />
        <StatTile label="Info" value={stats.info} color="text-blue-400" />
        <StatTile label="Warnings" value={stats.warn} color="text-amber-400" />
        <StatTile label="Errors" value={stats.error} color="text-red-400" />
        <StatTile label="Fatal" value={stats.fatal} color="text-red-600" />
      </div>

      {/* Actions Bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          {/* Level Filter */}
          <Select value={levelFilter} onValueChange={setLevelFilter}>
            <SelectTrigger className="w-[130px] h-8 text-xs">
              <Filter className="h-3 w-3 mr-1" />
              <SelectValue placeholder="Level" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Levels</SelectItem>
              <SelectItem value="errors">Errors Only</SelectItem>
              <SelectItem value="warn">Warnings</SelectItem>
              <SelectItem value="info">Info</SelectItem>
              <SelectItem value="debug">Debug</SelectItem>
            </SelectContent>
          </Select>

          {/* Category Filter */}
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="w-[130px] h-8 text-xs">
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Categories</SelectItem>
              <SelectItem value="lifecycle">Lifecycle</SelectItem>
              <SelectItem value="trade">Trade</SelectItem>
              <SelectItem value="connection">Connection</SelectItem>
              <SelectItem value="risk">Risk</SelectItem>
              <SelectItem value="config">Config</SelectItem>
              <SelectItem value="system">System</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2">
          {errorCount > 0 && configId && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => clearErrorsMutation.mutate()}
              disabled={clearErrorsMutation.isPending}
              className="h-8 text-xs"
            >
              <CheckCircle className="h-3 w-3 mr-1" />
              Clear Errors
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
            className="h-8 w-8 p-0"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Logs List */}
      <ScrollArea className="h-[400px] rounded-lg border border-white/10 bg-black/20">
        {isLoading ? (
          <div className="flex items-center justify-center h-32">
            <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <Info className="h-8 w-8 mb-2" />
            <p className="text-sm">No logs found</p>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {logs.map((log) => (
              <LogEntry key={log.id} log={log} />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

function StatTile({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-2 text-center">
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-muted-foreground uppercase">{label}</div>
    </div>
  );
}

function LogEntry({ log }: { log: BotLog }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`rounded-lg border p-3 cursor-pointer transition-all hover:bg-white/5 ${
        log.level === "error" || log.level === "fatal"
          ? "border-red-500/20 bg-red-500/5"
          : log.level === "warn"
          ? "border-amber-500/20 bg-amber-500/5"
          : "border-white/5 bg-white/[0.02]"
      }`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-start gap-3">
        {/* Level Icon */}
        <div className="mt-0.5">{LEVEL_ICONS[log.level]}</div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={`text-[10px] ${LEVEL_COLORS[log.level]}`}>
              {log.level.toUpperCase()}
            </Badge>
            <Badge variant="outline" className="text-[10px] border-white/10 gap-1">
              {CATEGORY_ICONS[log.category]}
              {log.category}
            </Badge>
            {log.symbol && (
              <Badge variant="outline" className="text-[10px] border-white/10">
                {log.symbol}
              </Badge>
            )}
            {log.error_code && (
              <Badge variant="outline" className="text-[10px] border-red-500/30 text-red-300">
                {log.error_code}
              </Badge>
            )}
          </div>

          <p className="text-sm text-white mt-1">{log.message}</p>

          <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground">
            <span>{formatDistanceToNow(new Date(log.created_at), { addSuffix: true })}</span>
            {log.source && (
              <>
                <span>•</span>
                <span>{log.source}</span>
              </>
            )}
            {log.environment && (
              <>
                <span>•</span>
                <span className="capitalize">{log.environment}</span>
              </>
            )}
          </div>

          {/* Expanded Details */}
          {expanded && (
            <div className="mt-3 pt-3 border-t border-white/10 space-y-2">
              <div className="text-[10px] text-muted-foreground">
                <span className="font-medium">Time:</span>{" "}
                {format(new Date(log.created_at), "yyyy-MM-dd HH:mm:ss.SSS")}
              </div>
              {log.error_type && (
                <div className="text-[10px] text-muted-foreground">
                  <span className="font-medium">Error Type:</span> {log.error_type}
                </div>
              )}
              {log.stack_trace && (
                <div className="mt-2">
                  <div className="text-[10px] font-medium text-muted-foreground mb-1">Stack Trace:</div>
                  <pre className="text-[10px] bg-black/40 rounded p-2 overflow-x-auto text-red-300">
                    {log.stack_trace}
                  </pre>
                </div>
              )}
              {Object.keys(log.details).length > 0 && (
                <div className="mt-2">
                  <div className="text-[10px] font-medium text-muted-foreground mb-1">Details:</div>
                  <pre className="text-[10px] bg-black/40 rounded p-2 overflow-x-auto text-slate-300">
                    {JSON.stringify(log.details, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}










