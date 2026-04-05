/**
 * AdvancedFiltersSheet - Left sheet with query-builder blocks for advanced filters
 */

import { useState } from 'react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from '../ui/sheet';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';
import { Separator } from '../ui/separator';
import { cn } from '../../lib/utils';
import {
  Zap,
  Shield,
  Activity,
  RotateCcw,
  Save,
  X,
} from 'lucide-react';
import { AdvancedFilters, DEFAULT_ADVANCED_FILTERS } from './types';

interface AdvancedFiltersSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: AdvancedFilters;
  onChange: (filters: AdvancedFilters) => void;
  onSaveAsView?: () => void;
}

interface FilterBlockProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}

function FilterBlock({ title, icon, children }: FilterBlockProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
        {icon}
        {title}
      </div>
      <div className="space-y-4 pl-6">
        {children}
      </div>
    </div>
  );
}

interface RangeInputProps {
  label: string;
  minValue?: number;
  maxValue?: number;
  onMinChange: (value?: number) => void;
  onMaxChange: (value?: number) => void;
  unit?: string;
  step?: number;
}

function RangeInput({ 
  label, 
  minValue, 
  maxValue, 
  onMinChange, 
  onMaxChange, 
  unit = '',
  step = 1,
}: RangeInputProps) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Input
            type="number"
            placeholder="Min"
            value={minValue ?? ''}
            onChange={(e) => onMinChange(e.target.value ? parseFloat(e.target.value) : undefined)}
            step={step}
            className="h-8 pr-8"
          />
          {unit && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
              {unit}
            </span>
          )}
        </div>
        <span className="text-muted-foreground">–</span>
        <div className="relative flex-1">
          <Input
            type="number"
            placeholder="Max"
            value={maxValue ?? ''}
            onChange={(e) => onMaxChange(e.target.value ? parseFloat(e.target.value) : undefined)}
            step={step}
            className="h-8 pr-8"
          />
          {unit && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
              {unit}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function AdvancedFiltersSheet({
  open,
  onOpenChange,
  filters,
  onChange,
  onSaveAsView,
}: AdvancedFiltersSheetProps) {
  const hasFilters = Object.entries(filters).some(([key, value]) => {
    if (value === undefined) return false;
    if (typeof value === 'string' && value === 'all') return false;
    return true;
  });
  
  const resetFilters = () => {
    onChange(DEFAULT_ADVANCED_FILTERS);
  };
  
  const updateFilter = <K extends keyof AdvancedFilters>(
    key: K,
    value: AdvancedFilters[K]
  ) => {
    onChange({ ...filters, [key]: value });
  };
  
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[420px] sm:w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            Advanced Filters
            {hasFilters && (
              <span className="h-2 w-2 rounded-full bg-amber-500" />
            )}
          </SheetTitle>
          <SheetDescription>
            Fine-tune your trade cohort with execution, risk, and market filters.
          </SheetDescription>
        </SheetHeader>
        
        <div className="py-6 space-y-8">
          {/* Execution Quality Block */}
          <FilterBlock 
            title="Execution Quality" 
            icon={<Zap className="h-4 w-4 text-blue-500" />}
          >
            <RangeInput
              label="Slippage"
              minValue={filters.slippageMin}
              maxValue={filters.slippageMax}
              onMinChange={(v) => updateFilter('slippageMin', v)}
              onMaxChange={(v) => updateFilter('slippageMax', v)}
              unit="bps"
              step={0.1}
            />
            
            <RangeInput
              label="Latency"
              minValue={filters.latencyMin}
              maxValue={filters.latencyMax}
              onMinChange={(v) => updateFilter('latencyMin', v)}
              onMaxChange={(v) => updateFilter('latencyMax', v)}
              unit="ms"
              step={1}
            />
            
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Fill Type</Label>
              <Select
                value={filters.fillType || 'all'}
                onValueChange={(v) => updateFilter('fillType', v as 'maker' | 'taker' | 'all')}
              >
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="maker">Maker Only</SelectItem>
                  <SelectItem value="taker">Taker Only</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </FilterBlock>
          
          <Separator className="bg-border" />
          
          {/* Risk Block */}
          <FilterBlock 
            title="Risk Parameters" 
            icon={<Shield className="h-4 w-4 text-amber-500" />}
          >
            <RangeInput
              label="Exposure at Entry"
              minValue={filters.exposureMin}
              maxValue={filters.exposureMax}
              onMinChange={(v) => updateFilter('exposureMin', v)}
              onMaxChange={(v) => updateFilter('exposureMax', v)}
              unit="%"
              step={0.5}
            />
            
            <RangeInput
              label="Leverage"
              minValue={filters.leverageMin}
              maxValue={filters.leverageMax}
              onMinChange={(v) => updateFilter('leverageMin', v)}
              onMaxChange={(v) => updateFilter('leverageMax', v)}
              unit="x"
              step={0.5}
            />
            
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Risk Gate Result</Label>
              <Select
                value={filters.riskGateResult || 'all'}
                onValueChange={(v) => updateFilter('riskGateResult', v as 'passed' | 'blocked' | 'all')}
              >
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="passed">Passed Only</SelectItem>
                  <SelectItem value="blocked">Blocked Only</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <RangeInput
              label="MAE (Max Adverse Excursion)"
              minValue={filters.maeMin}
              maxValue={filters.maeMax}
              onMinChange={(v) => updateFilter('maeMin', v)}
              onMaxChange={(v) => updateFilter('maeMax', v)}
              unit="bps"
              step={1}
            />
            
            <RangeInput
              label="MFE (Max Favorable Excursion)"
              minValue={filters.mfeMin}
              maxValue={filters.mfeMax}
              onMinChange={(v) => updateFilter('mfeMin', v)}
              onMaxChange={(v) => updateFilter('mfeMax', v)}
              unit="bps"
              step={1}
            />
          </FilterBlock>
          
          <Separator className="bg-border" />
          
          {/* Market Regime Block */}
          <FilterBlock 
            title="Market Regime" 
            icon={<Activity className="h-4 w-4 text-emerald-500" />}
          >
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Volatility Bucket</Label>
              <Select
                value={filters.volBucket || 'all'}
                onValueChange={(v) => updateFilter('volBucket', v as 'low' | 'medium' | 'high' | 'all')}
              >
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Volatility</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Spread Bucket</Label>
              <Select
                value={filters.spreadBucket || 'all'}
                onValueChange={(v) => updateFilter('spreadBucket', v as 'tight' | 'normal' | 'wide' | 'all')}
              >
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Spreads</SelectItem>
                  <SelectItem value="tight">Tight</SelectItem>
                  <SelectItem value="normal">Normal</SelectItem>
                  <SelectItem value="wide">Wide</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Trading Session</Label>
              <Select
                value={filters.session || 'all'}
                onValueChange={(v) => updateFilter('session', v as 'asia' | 'europe' | 'us' | 'all')}
              >
                <SelectTrigger className="h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Sessions</SelectItem>
                  <SelectItem value="asia">Asia (00:00-08:00 UTC)</SelectItem>
                  <SelectItem value="europe">Europe (08:00-16:00 UTC)</SelectItem>
                  <SelectItem value="us">US (16:00-00:00 UTC)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </FilterBlock>
        </div>
        
        <SheetFooter className="flex flex-row gap-2 pt-4 border-t border-border">
          <Button
            variant="outline"
            size="sm"
            onClick={resetFilters}
            disabled={!hasFilters}
            className="gap-1.5"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </Button>
          {onSaveAsView && (
            <Button
              variant="outline"
              size="sm"
              onClick={onSaveAsView}
              className="gap-1.5"
            >
              <Save className="h-3.5 w-3.5" />
              Save as View
            </Button>
          )}
          <div className="flex-1" />
          <Button
            size="sm"
            onClick={() => onOpenChange(false)}
            className="gap-1.5"
          >
            Apply Filters
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export default AdvancedFiltersSheet;

