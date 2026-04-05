/**
 * Scope Selector Component
 * 
 * Dropdown for selecting viewing scope: Fleet | Exchange Account | Bot
 * Shows exchange accounts grouped with their bots.
 */

import * as React from 'react';
import {
  ChevronDown,
  Building2,
  Bot,
  Layers,
  Circle,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { useScopeStore, type ScopeLevel, type Environment, type TimeWindow } from '@/store/scope-store';
import { useExchangeAccounts } from '@/lib/api/exchange-accounts-hooks';
import { useBotInstances } from '@/lib/api/hooks';

// =============================================================================
// Exchange Logo Component
// =============================================================================

// Inline SVG logos for reliability
function BinanceLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 126.61 126.61" className={cn("h-4 w-4", className)}>
      <g fill="#F3BA2F">
        <path d="M38.73 53.2l24.59-24.58 24.6 24.6 14.3-14.31L63.32 0l-38.9 38.9z"/>
        <path d="M0 63.31l14.3-14.31 14.31 14.31-14.31 14.3z"/>
        <path d="M38.73 73.41l24.59 24.59 24.6-24.6 14.31 14.29-38.9 38.91-38.91-38.88-.01-.02z"/>
        <path d="M97.99 63.31l14.3-14.31 14.32 14.31-14.31 14.3z"/>
        <path d="M77.83 63.3l-14.51-14.52-10.73 10.73-1.24 1.23-2.54 2.54 14.51 14.53 14.52-14.51z"/>
      </g>
    </svg>
  );
}

function OkxLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={cn("h-4 w-4", className)}>
      <rect width="40" height="40" rx="8" fill="currentColor" className="text-foreground"/>
      <g fill="hsl(var(--background))">
        <rect x="8" y="8" width="10" height="10" rx="1"/>
        <rect x="22" y="8" width="10" height="10" rx="1"/>
        <rect x="8" y="22" width="10" height="10" rx="1"/>
        <rect x="22" y="22" width="10" height="10" rx="1"/>
        <rect x="15" y="15" width="10" height="10" rx="1"/>
      </g>
    </svg>
  );
}

function BybitLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 200 200" className={cn("h-4 w-4", className)}>
      <defs>
        <linearGradient id="bybit-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#F7A600"/>
          <stop offset="100%" stopColor="#FF6B00"/>
        </linearGradient>
      </defs>
      <g fill="url(#bybit-gradient)">
        <path d="M100 0C44.77 0 0 44.77 0 100s44.77 100 100 100 100-44.77 100-100S155.23 0 100 0zm0 180c-44.11 0-80-35.89-80-80s35.89-80 80-80 80 35.89 80 80-35.89 80-80 80z"/>
        <path d="M140 70H90c-5.52 0-10 4.48-10 10v40c0 5.52 4.48 10 10 10h50c5.52 0 10-4.48 10-10V80c0-5.52-4.48-10-10-10zm-10 40h-30V90h30v20z"/>
        <circle cx="60" cy="100" r="15"/>
      </g>
    </svg>
  );
}

const EXCHANGE_COLORS: Record<string, string> = {
  binance: 'text-yellow-500',
  okx: 'text-foreground',
  bybit: 'text-orange-500',
};

export function ExchangeLogo({ venue, className }: { venue: string; className?: string }) {
  const v = venue.toLowerCase();
  
  if (v === 'binance') {
    return <BinanceLogo className={className} />;
  }
  if (v === 'okx') {
    return <OkxLogo className={className} />;
  }
  if (v === 'bybit') {
    return <BybitLogo className={className} />;
  }
  
  // Fallback: show venue initial in a colored circle
  return (
    <span className={cn(
      "h-4 w-4 flex items-center justify-center rounded text-[10px] font-bold bg-muted",
      EXCHANGE_COLORS[v] || 'text-muted-foreground',
      className
    )}>
      {venue.charAt(0).toUpperCase()}
    </span>
  );
}

// =============================================================================
// Main Scope Selector
// =============================================================================

export function ScopeSelector() {
  const [open, setOpen] = React.useState(false);
  const {
    level,
    exchangeAccountId,
    exchangeAccountName,
    botId,
    botName,
    setFleetScope,
    setExchangeScope,
    setBotScope,
  } = useScopeStore();

  const { data: accounts = [], isLoading } = useExchangeAccounts();
  const { data: botsData } = useBotInstances();

  // Map bots to their exchange accounts
  const botsByExchange = React.useMemo(() => {
    const map: Record<string, { id: string; name: string }[]> = {};
    const bots = botsData?.bots || [];
    bots.forEach((bot) => {
      (bot.exchangeConfigs || []).forEach((cfg: any) => {
        if (!cfg.exchange_account_id) return;
        map[cfg.exchange_account_id] = map[cfg.exchange_account_id] || [];
        map[cfg.exchange_account_id].push({ id: bot.id, name: bot.name });
      });
    });
    return map;
  }, [botsData]);
  
  // Auto-select the first exchange (and its active bot if present) so scopes are never null
  React.useEffect(() => {
    if (isLoading) return;
    // If nothing is available, reset to fleet to avoid stale persisted selections
    if (accounts.length === 0) {
      setFleetScope();
      return;
    }
    
    const first = accounts[0];
    const exchangeLabel = `${first.label} (${first.venue.toUpperCase()})`;
    
    // If nothing selected yet, default to exchange scope (only when not in fleet scope)
    if (!exchangeAccountId && level !== 'fleet') {
      setExchangeScope(first.id, exchangeLabel);
      if (first.active_bot_id && first.active_bot_name) {
        setBotScope(first.id, exchangeLabel, first.active_bot_id, first.active_bot_name);
      }
      return;
    }
  }, [accounts, isLoading, exchangeAccountId, level, setExchangeScope, setBotScope]);

  // Get current label
  const getCurrentLabel = () => {
    switch (level) {
      case 'fleet':
        return 'Fleet';
      case 'exchange':
        return exchangeAccountName || 'Exchange Account';
      case 'bot':
        return botName || 'Bot';
      default:
        return 'Fleet';
    }
  };

  // Extract venue from account name like "Test Account (BINANCE)" -> "binance"
  const getVenueFromName = (name: string | null): string | null => {
    if (!name) return null;
    const match = name.match(/\(([^)]+)\)$/);
    return match ? match[1].toLowerCase() : null;
  };

  // Get current icon
  const getCurrentIcon = () => {
    switch (level) {
      case 'fleet':
        return <Layers className="h-4 w-4" />;
      case 'exchange': {
        const venue = getVenueFromName(exchangeAccountName);
        return venue ? <ExchangeLogo venue={venue} /> : <Building2 className="h-4 w-4" />;
      }
      case 'bot':
        return <Bot className="h-4 w-4" />;
      default:
        return <Layers className="h-4 w-4" />;
    }
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button 
          className={cn(
            "w-full flex items-center gap-2 justify-between h-10 px-3 rounded-lg text-sm font-medium",
            "backdrop-blur-xl transition-all duration-200",
            // Dark mode (default) - frosted glass
            "bg-white/[0.08] border border-white/[0.12] text-foreground",
            "shadow-[0_2px_8px_rgba(0,0,0,0.2)]",
            "hover:bg-white/[0.12] hover:border-white/[0.18]",
            // Light mode - clean white with subtle shadow
            "light:bg-white light:border-slate-200 light:text-slate-700",
            "light:shadow-sm",
            "light:hover:bg-slate-50 light:hover:border-slate-300"
          )}
        >
          <span className="flex items-center gap-2">
            {getCurrentIcon()}
            <span className="truncate font-medium">{getCurrentLabel()}</span>
          </span>
          <ChevronDown className="h-4 w-4 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent 
        align="start" 
        className={cn(
          "w-[var(--radix-dropdown-menu-trigger-width)] min-w-[220px] rounded-xl p-1.5",
          "backdrop-blur-2xl",
          // Dark mode (default) - frosted glass panel
          "bg-white/[0.06] border border-white/[0.1]",
          "shadow-[0_8px_32px_rgba(0,0,0,0.4)]",
          // Light mode - clean white panel
          "light:bg-white light:border-slate-200",
          "light:shadow-lg light:shadow-slate-200/50"
        )}
      >
        {/* Fleet option */}
        <DropdownMenuItem
          onClick={() => {
            setFleetScope();
            setOpen(false);
          }}
          className={cn(
            "rounded-lg transition-all cursor-pointer",
            "hover:bg-white/[0.08] light:hover:bg-slate-100",
            level === 'fleet' && "bg-white/[0.1] light:bg-slate-100"
          )}
        >
          <Layers className="mr-2 h-4 w-4" />
          <span>Fleet (All)</span>
        </DropdownMenuItem>

        <DropdownMenuSeparator className="my-1.5 bg-white/[0.08] light:bg-slate-200" />
        <DropdownMenuLabel className="text-[11px] uppercase tracking-wider text-white/50 light:text-slate-500 font-semibold px-2 py-1">
          Exchange Accounts
        </DropdownMenuLabel>

        {isLoading ? (
          <div className="px-3 py-6 text-center">
            <div className="inline-flex items-center gap-2 text-sm text-white/60 light:text-slate-500">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white/70 light:border-slate-300 light:border-t-slate-600" />
              <span>Loading accounts...</span>
            </div>
          </div>
        ) : accounts.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <Building2 className="h-8 w-8 mx-auto mb-2 text-white/30 light:text-slate-300" />
            <p className="text-sm text-white/60 light:text-slate-500">No exchange accounts</p>
            <p className="text-xs text-white/40 light:text-slate-400 mt-1">Add one in Settings</p>
          </div>
        ) : (
          accounts.map((account) => (
            <ExchangeAccountItem
              key={account.id}
              account={account}
              bots={botsByExchange[account.id] || []}
              isSelected={exchangeAccountId === account.id}
              selectedBotId={botId}
              onSelectAccount={() => {
                setExchangeScope(account.id, `${account.label} (${account.venue.toUpperCase()})`);
                setOpen(false);
              }}
              onSelectBot={(bot) => {
                setBotScope(
                  account.id,
                  `${account.label} (${account.venue.toUpperCase()})`,
                  bot.id,
                  bot.name
                );
                setOpen(false);
              }}
            />
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// =============================================================================
// Exchange Account Item with Bots
// =============================================================================

interface ExchangeAccountItemProps {
  account: {
    id: string;
    venue: string;
    label: string;
    environment: string;
    status: string;
    kill_switch_enabled?: boolean;
    running_bot_count?: number;
    bot_count?: number;
    active_bot_id?: string;
    active_bot_name?: string;
  };
  bots: { id: string; name: string }[];
  isSelected: boolean;
  selectedBotId: string | null;
  onSelectAccount: () => void;
  onSelectBot: (bot: { id: string; name: string }) => void;
}

function ExchangeAccountItem({
  account,
  bots,
  isSelected,
  selectedBotId,
  onSelectAccount,
  onSelectBot,
}: ExchangeAccountItemProps) {
  const [expanded, setExpanded] = React.useState(isSelected);

  // Status indicator
  const getStatusIcon = () => {
    if (account.kill_switch_enabled) {
      return <AlertTriangle className="h-3 w-3 text-destructive" />;
    }
    if (account.status === 'verified') {
      return <CheckCircle2 className="h-3 w-3 text-green-500" />;
    }
    return <Circle className="h-3 w-3 text-muted-foreground" />;
  };

  // Environment badge colors - theme aware
  const getEnvBadge = () => {
    const colors: Record<string, string> = {
      live: 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border-emerald-500/40',
      paper: 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/40',
      dev: 'bg-sky-500/20 text-sky-600 dark:text-sky-400 border-sky-500/40',
    };
    return colors[account.environment] || colors.dev;
  };

  return (
    <div className="space-y-0.5">
      {/* Account row */}
      <DropdownMenuItem
        onClick={(e) => {
          e.preventDefault();
          if (expanded) {
            onSelectAccount();
          } else {
            setExpanded(true);
          }
        }}
        className={cn(
          'flex items-center justify-between rounded-lg transition-all cursor-pointer',
          'hover:bg-white/[0.08] light:hover:bg-slate-100',
          isSelected && !selectedBotId && "bg-white/[0.1] light:bg-slate-100"
        )}
      >
        <span className="flex items-center gap-2.5">
          {getStatusIcon()}
          <ExchangeLogo venue={account.venue} className="h-5 w-5" />
          <span className="truncate max-w-[120px] font-medium">
            {account.label}
          </span>
        </span>
        <Badge variant="outline" className={cn('text-[10px] px-1.5 py-0 font-semibold', getEnvBadge())}>
          {account.environment.toUpperCase()}
        </Badge>
      </DropdownMenuItem>

      {/* Bots under this account */}
      {expanded && bots.map((b) => (
        <DropdownMenuItem
          key={b.id}
          onClick={() => onSelectBot({ id: b.id, name: b.name })}
          className={cn(
            'pl-9 ml-2 rounded-lg transition-all cursor-pointer',
            'border-l-2 border-white/10 light:border-slate-200',
            'hover:bg-white/[0.08] light:hover:bg-slate-100',
            selectedBotId === b.id && "bg-white/[0.1] light:bg-slate-100 border-l-primary"
          )}
        >
          <Bot className="mr-2 h-4 w-4 opacity-70" />
          <span className="truncate">{b.name}</span>
          <span className="ml-auto flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          </span>
        </DropdownMenuItem>
      ))}
    </div>
  );
}

// =============================================================================
// Environment Filter
// =============================================================================

export function EnvironmentFilter() {
  const { environment, setEnvironment } = useScopeStore();

  const options: { value: Environment; label: string }[] = [
    { value: 'all', label: 'All Env' },
    { value: 'live', label: 'Live' },
    { value: 'paper', label: 'Paper' },
    { value: 'dev', label: 'Dev' },
  ];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1">
          <span>{options.find(o => o.value === environment)?.label || 'All Env'}</span>
          <ChevronDown className="h-3 w-3 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {options.map((option) => (
          <DropdownMenuItem
            key={option.value}
            onClick={() => setEnvironment(option.value)}
            className={cn(environment === option.value && 'bg-accent')}
          >
            {option.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// =============================================================================
// Time Window Filter
// =============================================================================

export function TimeWindowFilter() {
  const { timeWindow, setTimeWindow } = useScopeStore();

  const options: { value: TimeWindow; label: string }[] = [
    { value: '15m', label: '15m' },
    { value: '1h', label: '1h' },
    { value: '4h', label: '4h' },
    { value: '24h', label: '24h' },
    { value: '7d', label: '7d' },
  ];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1">
          <span>{timeWindow}</span>
          <ChevronDown className="h-3 w-3 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {options.map((option) => (
          <DropdownMenuItem
            key={option.value}
            onClick={() => setTimeWindow(option.value)}
            className={cn(timeWindow === option.value && 'bg-accent')}
          >
            {option.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// =============================================================================
// Scope Badge (for page headers)
// =============================================================================

export function ScopeBadge({ className }: { className?: string }) {
  const { level, exchangeAccountName, botName } = useScopeStore();

  const getLabel = () => {
    switch (level) {
      case 'fleet':
        return 'Fleet';
      case 'exchange':
        return exchangeAccountName || 'Exchange';
      case 'bot':
        return botName || 'Bot';
      default:
        return 'Fleet';
    }
  };

  const getColor = () => {
    switch (level) {
      case 'fleet':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/50';
      case 'exchange':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/50';
      case 'bot':
        return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/50';
      default:
        return 'bg-gray-500/20 text-gray-400 border-gray-500/50';
    }
  };

  return (
    <Badge variant="outline" className={cn('font-normal', getColor(), className)}>
      Scope: {getLabel()}
    </Badge>
  );
}

// =============================================================================
// Combined Header Controls
// =============================================================================

export function ScopeControls() {
  return (
    <div className="flex items-center gap-2">
      <ScopeSelector />
      <TimeWindowFilter />
      <EnvironmentFilter />
    </div>
  );
}


