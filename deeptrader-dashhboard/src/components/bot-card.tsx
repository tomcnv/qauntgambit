/**
 * BotCard Component
 * 
 * Displays a bot instance with its exchange configurations.
 * Features:
 * - Expandable view to show exchange configs
 * - State badges (READY, RUNNING, PAUSED, ERROR)
 * - One-click activation
 * - Environment indicator
 */

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Play,
  Pause,
  AlertTriangle,
  CheckCircle,
  Clock,
  Settings,
  Trash2,
  Plus,
  Zap,
  Activity,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "./ui/card";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import type { BotInstance, BotExchangeConfig, BotConfigState, BotEnvironment } from "../lib/api/types";

interface BotCardProps {
  bot: BotInstance;
  onActivate?: (configId: string) => void;
  onDeactivate?: (configId: string) => void;
  onEditConfig?: (configId: string) => void;
  onDeleteConfig?: (configId: string) => void;
  onAddExchange?: (botId: string) => void;
  onEditBot?: (botId: string) => void;
  onDeleteBot?: (botId: string) => void;
  isLoading?: boolean;
}

const STATE_COLORS: Record<BotConfigState, string> = {
  created: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  ready: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  running: "bg-blue-500/20 text-blue-300 border-blue-500/30 animate-pulse",
  paused: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  error: "bg-red-500/20 text-red-300 border-red-500/30",
  decommissioned: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  blocked: "bg-orange-500/20 text-orange-300 border-orange-500/30",
};

const STATE_ICONS: Record<BotConfigState, React.ReactNode> = {
  created: <Clock className="h-3 w-3" />,
  ready: <CheckCircle className="h-3 w-3" />,
  running: <Activity className="h-3 w-3" />,
  paused: <Pause className="h-3 w-3" />,
  error: <AlertTriangle className="h-3 w-3" />,
  decommissioned: <Trash2 className="h-3 w-3" />,
  blocked: <AlertTriangle className="h-3 w-3" />,
};

const ENV_COLORS: Record<BotEnvironment, string> = {
  dev: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  paper: "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  live: "bg-green-500/20 text-green-300 border-green-500/30",
};

// Combined trading mode badge helpers
function getTradingModeLabel(isDemo: boolean | undefined, environment: string): string {
  if (isDemo && environment === 'live') return '🧪 Demo Trading';
  if (isDemo && environment === 'paper') return '🧪 Demo Paper';
  if (!isDemo && environment === 'live') return '🔥 Live Trading';
  if (!isDemo && environment === 'paper') return '📝 Paper Mode';
  return '🔧 Dev Mode';
}

function getTradingModeBadgeStyle(isDemo: boolean | undefined, environment: string): string {
  if (isDemo && environment === 'live') return 'border-amber-500/50 text-amber-400 bg-amber-500/20';
  if (isDemo && environment === 'paper') return 'border-amber-500/30 text-amber-300 bg-amber-500/10';
  if (!isDemo && environment === 'live') return 'border-red-500/50 text-red-400 bg-red-500/20';
  if (!isDemo && environment === 'paper') return 'border-blue-500/50 text-blue-400 bg-blue-500/20';
  return 'border-purple-500/50 text-purple-400 bg-purple-500/20';
}

export default function BotCard({
  bot,
  onActivate,
  onDeactivate,
  onEditConfig,
  onDeleteConfig,
  onAddExchange,
  onEditBot,
  onDeleteBot,
  isLoading,
}: BotCardProps) {
  const [expanded, setExpanded] = useState(false);
  const configs = bot.exchangeConfigs || [];
  const activeConfig = configs.find((c) => c.is_active);
  const hasRunningConfig = configs.some((c) => c.state === "running");

  return (
    <Card className={`border-white/5 bg-black/30 transition-all ${activeConfig ? "ring-1 ring-primary/40" : ""}`}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setExpanded(!expanded)}
              className="rounded-lg p-1.5 hover:bg-white/10 transition"
              aria-label={expanded ? "Collapse" : "Expand"}
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold text-white">{bot.name}</h3>
                {activeConfig && (
                  <Badge className="bg-primary/20 text-primary border-primary/30 text-[10px] uppercase">
                    Active
                  </Badge>
                )}
                {hasRunningConfig && (
                  <span className="flex items-center gap-1 text-xs text-blue-400">
                    <Zap className="h-3 w-3" />
                    Running
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1">
                {bot.template_name && (
                  <span className="text-xs text-muted-foreground">
                    Strategy: {bot.template_name}
                  </span>
                )}
                {bot.allocator_role && (
                  <Badge variant="outline" className="text-[10px] uppercase border-white/10">
                    {bot.allocator_role}
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEditBot?.(bot.id)}
              className="h-8 w-8 p-0"
            >
              <Settings className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDeleteBot?.(bot.id)}
              className="h-8 w-8 p-0 hover:text-red-400"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Summary row */}
        <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
          <span>{configs.length} exchange{configs.length !== 1 ? "s" : ""}</span>
          {activeConfig && (
            <>
              <span>•</span>
              <span className="flex items-center gap-1">
                <span className="font-medium text-white">{activeConfig.exchange}</span>
                <Badge className={`text-[10px] ${ENV_COLORS[activeConfig.environment]}`}>
                  {activeConfig.environment}
                </Badge>
              </span>
              {activeConfig.trading_capital_usd && (
                <>
                  <span>•</span>
                  <span>${activeConfig.trading_capital_usd.toLocaleString()}</span>
                </>
              )}
            </>
          )}
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="pt-2">
          <div className="space-y-3">
            {configs.length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/10 p-6 text-center">
                <p className="text-sm text-muted-foreground">No exchange connections configured</p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => onAddExchange?.(bot.id)}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add Exchange
                </Button>
              </div>
            ) : (
              configs.map((config) => (
                <ExchangeConfigRow
                  key={config.id}
                  config={config}
                  botId={bot.id}
                  onActivate={onActivate}
                  onDeactivate={onDeactivate}
                  onEdit={onEditConfig}
                  onDelete={onDeleteConfig}
                  isLoading={isLoading}
                />
              ))
            )}

            {configs.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="w-full border border-dashed border-white/10 hover:border-white/20"
                onClick={() => onAddExchange?.(bot.id)}
              >
                <Plus className="h-4 w-4 mr-2" />
                Add Exchange Connection
              </Button>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

interface ExchangeConfigRowProps {
  config: BotExchangeConfig;
  botId: string;
  onActivate?: (configId: string) => void;
  onDeactivate?: (configId: string) => void;
  onEdit?: (configId: string) => void;
  onDelete?: (configId: string) => void;
  isLoading?: boolean;
}

function ExchangeConfigRow({
  config,
  botId,
  onActivate,
  onDeactivate,
  onEdit,
  onDelete,
  isLoading,
}: ExchangeConfigRowProps) {
  return (
    <div
      className={`rounded-xl border p-4 transition ${
        config.is_active
          ? "border-primary/40 bg-primary/5"
          : "border-white/5 bg-white/[0.02] hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex flex-col items-start gap-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-white capitalize">{config.exchange}</span>
              <Badge variant="outline" className={`text-[10px] ${getTradingModeBadgeStyle(config.is_demo, config.environment)}`}>
                {getTradingModeLabel(config.is_demo, config.environment)}
              </Badge>
              <Badge className={`text-[10px] ${STATE_COLORS[config.state]}`}>
                {STATE_ICONS[config.state]}
                <span className="ml-1">{config.state}</span>
              </Badge>
            </div>
            {config.credential_label && (
              <span className="text-xs text-muted-foreground">{config.credential_label}</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Stats */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            {config.trading_capital_usd && (
              <span>
                <span className="text-white font-medium">
                  ${config.trading_capital_usd.toLocaleString()}
                </span>
              </span>
            )}
            {config.enabled_symbols && config.enabled_symbols.length > 0 && (
              <span>
                {config.enabled_symbols.length} symbol{config.enabled_symbols.length !== 1 ? "s" : ""}
              </span>
            )}
            {config.trades_count > 0 && <span>{config.trades_count} trades</span>}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1">
            {config.is_active ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onDeactivate?.(config.id)}
                disabled={isLoading}
                className="h-8 text-amber-400 hover:text-amber-300"
              >
                <Pause className="h-4 w-4 mr-1" />
                Deactivate
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onActivate?.(config.id)}
                disabled={isLoading || config.state === "decommissioned"}
                className="h-8 text-emerald-400 hover:text-emerald-300"
              >
                <Play className="h-4 w-4 mr-1" />
                Activate
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit?.(config.id)}
              className="h-8 w-8 p-0"
            >
              <Settings className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete?.(config.id)}
              disabled={config.is_active}
              className="h-8 w-8 p-0 hover:text-red-400"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Error message */}
      {config.state === "error" && config.last_error && (
        <div className="mt-2 rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2 text-xs text-red-300">
          <AlertTriangle className="h-3 w-3 inline mr-1" />
          {config.last_error}
        </div>
      )}

      {/* Symbols preview */}
      {config.enabled_symbols && config.enabled_symbols.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {config.enabled_symbols.slice(0, 5).map((symbol) => (
            <Badge
              key={symbol}
              variant="outline"
              className="text-[10px] border-white/10 bg-white/5"
            >
              {symbol.replace("-USDT-SWAP", "")}
            </Badge>
          ))}
          {config.enabled_symbols.length > 5 && (
            <Badge variant="outline" className="text-[10px] border-white/10 bg-white/5">
              +{config.enabled_symbols.length - 5} more
            </Badge>
          )}
        </div>
      )}
    </div>
  );
}



