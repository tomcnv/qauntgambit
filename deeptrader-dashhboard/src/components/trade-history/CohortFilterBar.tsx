/**
 * CohortFilterBar - Always-visible filter row for Trade History
 */

import { useState, useMemo } from 'react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Input } from '../ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '../ui/popover';
import { Card } from '../ui/card';
import { cn } from '../../lib/utils';
import {
  Calendar,
  Filter,
  ChevronDown,
  X,
  TrendingUp,
  TrendingDown,
  Minus,
  SlidersHorizontal,
} from 'lucide-react';
import { CohortFilters, TimeRange, Outcome, Side, DEFAULT_COHORT_FILTERS } from './types';

interface CohortFilterBarProps {
  filters: CohortFilters;
  onChange: (filters: CohortFilters) => void;
  onOpenAdvanced: () => void;
  availableSymbols?: string[];
  availableStrategies?: { id: string; name: string }[];
  availableProfiles?: { id: string; name: string }[];
  hasAdvancedFilters?: boolean;
}

const TIME_RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: '1D', label: '1D' },
  { value: '7D', label: '7D' },
  { value: '30D', label: '30D' },
  { value: '90D', label: '90D' },
  { value: 'YTD', label: 'YTD' },
  { value: 'ALL', label: 'All' },
  { value: 'CUSTOM', label: 'Custom' },
];

export function CohortFilterBar({
  filters,
  onChange,
  onOpenAdvanced,
  availableSymbols = [],
  availableStrategies = [],
  availableProfiles = [],
  hasAdvancedFilters = false,
}: CohortFilterBarProps) {
  const [symbolSearch, setSymbolSearch] = useState('');
  
  const filteredSymbols = useMemo(() => {
    if (!symbolSearch) return availableSymbols.slice(0, 10);
    return availableSymbols
      .filter(s => s.toLowerCase().includes(symbolSearch.toLowerCase()))
      .slice(0, 10);
  }, [availableSymbols, symbolSearch]);
  
  const hasFilters = useMemo(() => {
    return (
      filters.symbols.length > 0 ||
      filters.strategies.length > 0 ||
      filters.profiles.length > 0 ||
      filters.outcome !== 'all' ||
      filters.side !== 'all' ||
      filters.minPnl !== undefined ||
      filters.maxPnl !== undefined
    );
  }, [filters]);
  
  const clearAllFilters = () => {
    onChange(DEFAULT_COHORT_FILTERS);
  };
  
  const toggleSymbol = (symbol: string) => {
    const newSymbols = filters.symbols.includes(symbol)
      ? filters.symbols.filter(s => s !== symbol)
      : [...filters.symbols, symbol];
    onChange({ ...filters, symbols: newSymbols });
  };
  
  const toggleStrategy = (strategyId: string) => {
    const newStrategies = filters.strategies.includes(strategyId)
      ? filters.strategies.filter(s => s !== strategyId)
      : [...filters.strategies, strategyId];
    onChange({ ...filters, strategies: newStrategies });
  };
  
  const toggleProfile = (profileId: string) => {
    const newProfiles = filters.profiles.includes(profileId)
      ? filters.profiles.filter(p => p !== profileId)
      : [...filters.profiles, profileId];
    onChange({ ...filters, profiles: newProfiles });
  };
  
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-3">
        {/* Time Range Chips */}
        <div className="flex items-center gap-1.5 border-r pr-4">
          {TIME_RANGE_OPTIONS.slice(0, 6).map(opt => (
            <button
              key={opt.value}
              onClick={() => onChange({ ...filters, timeRange: opt.value })}
              className={cn(
                "px-3 py-1.5 text-xs font-medium rounded-lg transition-all",
                filters.timeRange === opt.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground"
              )}
            >
              {opt.label}
            </button>
          ))}
          
          {/* Custom Date Range */}
          <Popover>
            <PopoverTrigger asChild>
              <button
                className={cn(
                  "px-3 py-1.5 text-xs font-medium rounded-lg transition-all flex items-center gap-1.5",
                  filters.timeRange === 'CUSTOM'
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground"
                )}
              >
                <Calendar className="h-3 w-3" />
                Custom
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-4" align="start">
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">From</label>
                  <Input
                    type="date"
                    value={filters.startDate || ''}
                    onChange={(e) => onChange({ 
                      ...filters, 
                      timeRange: 'CUSTOM',
                      startDate: e.target.value 
                    })}
                    className="h-9"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">To</label>
                  <Input
                    type="date"
                    value={filters.endDate || ''}
                    onChange={(e) => onChange({ 
                      ...filters, 
                      timeRange: 'CUSTOM',
                      endDate: e.target.value 
                    })}
                    className="h-9"
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>
        
        {/* Symbol Multi-Select */}
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className={cn(
                "h-8 gap-2",
                filters.symbols.length > 0 && "border-primary/50 bg-primary/10"
              )}
            >
              {filters.symbols.length > 0 ? (
                <>
                  <span>{filters.symbols.length} symbols</span>
                  <Badge variant="outline" className="h-4 px-1 text-[10px]">
                    {filters.symbols.length}
                  </Badge>
                </>
              ) : (
                <>
                  <span>Symbols</span>
                  <ChevronDown className="h-3 w-3 opacity-50" />
                </>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-64 p-3" align="start">
            <div className="space-y-3">
              <Input
                placeholder="Search symbols..."
                value={symbolSearch}
                onChange={(e) => setSymbolSearch(e.target.value)}
                className="h-8"
              />
              <div className="max-h-48 overflow-y-auto space-y-1">
                {filteredSymbols.map(symbol => (
                  <button
                    key={symbol}
                    onClick={() => toggleSymbol(symbol)}
                    className={cn(
                      "w-full text-left px-2 py-1.5 text-sm rounded-md transition-colors",
                      filters.symbols.includes(symbol)
                        ? "bg-primary/20 text-primary"
                        : "hover:bg-muted"
                    )}
                  >
                    {symbol}
                  </button>
                ))}
                {filteredSymbols.length === 0 && (
                  <p className="text-xs text-muted-foreground text-center py-2">
                    No symbols found
                  </p>
                )}
              </div>
              {filters.symbols.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full h-7 text-xs"
                  onClick={() => onChange({ ...filters, symbols: [] })}
                >
                  Clear selection
                </Button>
              )}
            </div>
          </PopoverContent>
        </Popover>
        
        {/* Strategy Multi-Select */}
        {availableStrategies.length > 0 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className={cn(
                  "h-8 gap-2",
                  filters.strategies.length > 0 && "border-primary/50 bg-primary/10"
                )}
              >
                {filters.strategies.length > 0 ? (
                  <>
                    <span>{filters.strategies.length} strategies</span>
                    <Badge variant="outline" className="h-4 px-1 text-[10px]">
                      {filters.strategies.length}
                    </Badge>
                  </>
                ) : (
                  <>
                    <span>Strategies</span>
                    <ChevronDown className="h-3 w-3 opacity-50" />
                  </>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-3" align="start">
              <div className="max-h-48 overflow-y-auto space-y-1">
                {availableStrategies.map(strategy => (
                  <button
                    key={strategy.id}
                    onClick={() => toggleStrategy(strategy.id)}
                    className={cn(
                      "w-full text-left px-2 py-1.5 text-sm rounded-md transition-colors",
                      filters.strategies.includes(strategy.id)
                        ? "bg-primary/20 text-primary"
                        : "hover:bg-muted"
                    )}
                  >
                    {strategy.name}
                  </button>
                ))}
              </div>
              {filters.strategies.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full h-7 text-xs mt-2"
                  onClick={() => onChange({ ...filters, strategies: [] })}
                >
                  Clear selection
                </Button>
              )}
            </PopoverContent>
          </Popover>
        )}
        
        {/* Profile Multi-Select */}
        {availableProfiles.length > 0 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className={cn(
                  "h-8 gap-2",
                  filters.profiles.length > 0 && "border-primary/50 bg-primary/10"
                )}
              >
                {filters.profiles.length > 0 ? (
                  <>
                    <span>{filters.profiles.length} profiles</span>
                    <Badge variant="outline" className="h-4 px-1 text-[10px]">
                      {filters.profiles.length}
                    </Badge>
                  </>
                ) : (
                  <>
                    <span>Profiles</span>
                    <ChevronDown className="h-3 w-3 opacity-50" />
                  </>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-3" align="start">
              <div className="max-h-48 overflow-y-auto space-y-1">
                {availableProfiles.map(profile => (
                  <button
                    key={profile.id}
                    onClick={() => toggleProfile(profile.id)}
                    className={cn(
                      "w-full text-left px-2 py-1.5 text-sm rounded-md transition-colors",
                      filters.profiles.includes(profile.id)
                        ? "bg-primary/20 text-primary"
                        : "hover:bg-muted"
                    )}
                  >
                    {profile.name}
                  </button>
                ))}
              </div>
              {filters.profiles.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full h-7 text-xs mt-2"
                  onClick={() => onChange({ ...filters, profiles: [] })}
                >
                  Clear selection
                </Button>
              )}
            </PopoverContent>
          </Popover>
        )}
        
        <div className="border-l pl-3 h-6" />
        
        {/* Outcome Toggle */}
        <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
          <button
            onClick={() => onChange({ ...filters, outcome: 'all' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all",
              filters.outcome === 'all'
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            All
          </button>
          <button
            onClick={() => onChange({ ...filters, outcome: 'win' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all flex items-center gap-1",
              filters.outcome === 'win'
                ? "bg-emerald-500 text-white"
                : "text-muted-foreground hover:text-emerald-500"
            )}
          >
            <TrendingUp className="h-3 w-3" />
            Win
          </button>
          <button
            onClick={() => onChange({ ...filters, outcome: 'loss' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all flex items-center gap-1",
              filters.outcome === 'loss'
                ? "bg-red-500 text-white"
                : "text-muted-foreground hover:text-red-500"
            )}
          >
            <TrendingDown className="h-3 w-3" />
            Loss
          </button>
          <button
            onClick={() => onChange({ ...filters, outcome: 'flat' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all flex items-center gap-1",
              filters.outcome === 'flat'
                ? "bg-muted-foreground text-background"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Minus className="h-3 w-3" />
            Flat
          </button>
        </div>
        
        {/* Side Toggle */}
        <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
          <button
            onClick={() => onChange({ ...filters, side: 'all' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all",
              filters.side === 'all'
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            All
          </button>
          <button
            onClick={() => onChange({ ...filters, side: 'long' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all",
              filters.side === 'long'
                ? "bg-emerald-500/80 text-white"
                : "text-muted-foreground hover:text-emerald-500"
            )}
          >
            Long
          </button>
          <button
            onClick={() => onChange({ ...filters, side: 'short' })}
            className={cn(
              "px-2.5 py-1 text-xs font-medium rounded-md transition-all",
              filters.side === 'short'
                ? "bg-red-500/80 text-white"
                : "text-muted-foreground hover:text-red-500"
            )}
          >
            Short
          </button>
        </div>
        
        <div className="flex-1" />
        
        {/* Advanced Filters Button */}
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenAdvanced}
          className={cn(
            "h-8 gap-2",
            hasAdvancedFilters && "border-amber-500/50 bg-amber-500/10"
          )}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Advanced
          {hasAdvancedFilters && (
            <Badge variant="outline" className="h-4 px-1 text-[10px] bg-amber-500/20 text-amber-500 border-amber-500/30">
              Active
            </Badge>
          )}
        </Button>
        
        {/* Clear All */}
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={clearAllFilters}
            className="h-8 gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
            Clear
          </Button>
        )}
      </div>
      
      {/* Active Filters Summary */}
      {(filters.symbols.length > 0 || filters.strategies.length > 0 || filters.profiles.length > 0) && (
        <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t">
          <span className="text-xs text-muted-foreground">Active:</span>
          {filters.symbols.map(symbol => (
            <Badge
              key={symbol}
              variant="outline"
              className="text-xs gap-1 cursor-pointer hover:bg-muted"
              onClick={() => toggleSymbol(symbol)}
            >
              {symbol}
              <X className="h-2.5 w-2.5" />
            </Badge>
          ))}
          {filters.strategies.map(id => {
            const strategy = availableStrategies.find(s => s.id === id);
            return (
              <Badge
                key={id}
                variant="outline"
                className="text-xs gap-1 cursor-pointer hover:bg-muted bg-blue-500/10 text-blue-500 border-blue-500/30"
                onClick={() => toggleStrategy(id)}
              >
                {strategy?.name || id}
                <X className="h-2.5 w-2.5" />
              </Badge>
            );
          })}
          {filters.profiles.map(id => {
            const profile = availableProfiles.find(p => p.id === id);
            return (
              <Badge
                key={id}
                variant="outline"
                className="text-xs gap-1 cursor-pointer hover:bg-muted bg-purple-500/10 text-purple-500 border-purple-500/30"
                onClick={() => toggleProfile(id)}
              >
                {profile?.name || id}
                <X className="h-2.5 w-2.5" />
              </Badge>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export default CohortFilterBar;
