/**
 * ColumnPresetsDropdown - Quick column set switching
 */

import { Button } from '../ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import { cn } from '../../lib/utils';
import {
  Columns,
  ChevronDown,
  Zap,
  Shield,
  FlaskConical,
  LayoutGrid,
  Check,
} from 'lucide-react';
import { ColumnPreset } from './types';

interface ColumnPresetsDropdownProps {
  value: ColumnPreset;
  onChange: (preset: ColumnPreset) => void;
}

const PRESETS: { value: ColumnPreset; label: string; description: string; icon: React.ReactNode }[] = [
  {
    value: 'execution',
    label: 'Execution',
    description: 'Slippage, latency, fills',
    icon: <Zap className="h-4 w-4 text-blue-500" />,
  },
  {
    value: 'risk',
    label: 'Risk',
    description: 'MAE/MFE, leverage, R-multiple',
    icon: <Shield className="h-4 w-4 text-amber-500" />,
  },
  {
    value: 'research',
    label: 'Research',
    description: 'Profiles, strategies, traces',
    icon: <FlaskConical className="h-4 w-4 text-purple-500" />,
  },
  {
    value: 'all',
    label: 'All Columns',
    description: 'Show everything',
    icon: <LayoutGrid className="h-4 w-4 text-muted-foreground" />,
  },
];

export function ColumnPresetsDropdown({ value, onChange }: ColumnPresetsDropdownProps) {
  const currentPreset = PRESETS.find(p => p.value === value) || PRESETS[3];
  
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-2"
        >
          <Columns className="h-3.5 w-3.5" />
          {currentPreset.label}
          <ChevronDown className="h-3 w-3 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Column Presets</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {PRESETS.map((preset) => (
          <DropdownMenuItem
            key={preset.value}
            className="cursor-pointer"
            onClick={() => onChange(preset.value)}
          >
            <div className="flex items-start gap-3 w-full">
              <div className="mt-0.5">{preset.icon}</div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{preset.label}</span>
                  {value === preset.value && (
                    <Check className="h-3.5 w-3.5 text-primary" />
                  )}
                </div>
                <span className="text-xs text-muted-foreground">{preset.description}</span>
              </div>
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default ColumnPresetsDropdown;

