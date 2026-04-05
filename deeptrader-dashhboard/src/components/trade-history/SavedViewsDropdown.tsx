/**
 * SavedViewsDropdown - Saved filter presets with localStorage persistence
 */

import { useState } from 'react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import { cn } from '../../lib/utils';
import {
  Bookmark,
  ChevronDown,
  Plus,
  Star,
  Trash2,
  Check,
} from 'lucide-react';
import { SavedView, CohortFilters, AdvancedFilters, ColumnPreset } from './types';

interface SavedViewsDropdownProps {
  views: SavedView[];
  currentFilters: CohortFilters;
  currentAdvancedFilters?: AdvancedFilters;
  currentColumnPreset: ColumnPreset;
  onApplyView: (view: SavedView) => void;
  onSaveView: (name: string, filters: CohortFilters, advancedFilters?: AdvancedFilters, columnPreset?: ColumnPreset) => SavedView;
  onDeleteView: (id: string) => void;
  onSetDefault: (id: string) => void;
}

export function SavedViewsDropdown({
  views,
  currentFilters,
  currentAdvancedFilters,
  currentColumnPreset,
  onApplyView,
  onSaveView,
  onDeleteView,
  onSetDefault,
}: SavedViewsDropdownProps) {
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [viewName, setViewName] = useState('');
  
  const handleSave = () => {
    if (!viewName.trim()) return;
    
    onSaveView(viewName.trim(), currentFilters, currentAdvancedFilters, currentColumnPreset);
    setViewName('');
    setSaveDialogOpen(false);
  };
  
  const defaultView = views.find(v => v.isDefault);
  
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-2"
          >
            <Bookmark className="h-3.5 w-3.5" />
            Saved Views
            {views.length > 0 && (
              <Badge variant="outline" className="h-4 px-1 text-[10px]">
                {views.length}
              </Badge>
            )}
            <ChevronDown className="h-3 w-3 opacity-50" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          <DropdownMenuLabel className="flex items-center justify-between">
            <span>Saved Views</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setSaveDialogOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          
          {views.length === 0 ? (
            <div className="px-2 py-4 text-center text-sm text-muted-foreground">
              <Bookmark className="h-8 w-8 mx-auto mb-2 opacity-30" />
              <p>No saved views yet</p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-2 gap-1.5"
                onClick={() => setSaveDialogOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" />
                Save current filters
              </Button>
            </div>
          ) : (
            <>
              {views.map(view => (
                <DropdownMenuItem
                  key={view.id}
                  className="flex items-center justify-between cursor-pointer group"
                  onClick={() => onApplyView(view)}
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {view.isDefault ? (
                      <Star className="h-3.5 w-3.5 text-amber-500 fill-amber-400 flex-shrink-0" />
                    ) : (
                      <Bookmark className="h-3.5 w-3.5 opacity-50 flex-shrink-0" />
                    )}
                    <span className="truncate">{view.name}</span>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {!view.isDefault && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-5 w-5 p-0"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSetDefault(view.id);
                        }}
                      >
                        <Star className="h-3 w-3" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-5 w-5 p-0 hover:text-red-500"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteView(view.id);
                      }}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </DropdownMenuItem>
              ))}
              
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="gap-2"
                onClick={() => setSaveDialogOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" />
                Save current as new view
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      
      {/* Save View Dialog */}
      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>Save View</DialogTitle>
            <DialogDescription>
              Save your current filter configuration for quick access later.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Input
              placeholder="View name (e.g., 'Winning BTC Longs')"
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              autoFocus
            />
            
            {/* Preview of what will be saved */}
            <div className="mt-4 p-3 rounded-lg bg-muted border space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Will save:</p>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline" className="text-xs">
                  {currentFilters.timeRange}
                </Badge>
                {currentFilters.symbols.length > 0 && (
                  <Badge variant="outline" className="text-xs">
                    {currentFilters.symbols.length} symbols
                  </Badge>
                )}
                {currentFilters.outcome !== 'all' && (
                  <Badge variant="outline" className="text-xs capitalize">
                    {currentFilters.outcome}
                  </Badge>
                )}
                {currentFilters.side !== 'all' && (
                  <Badge variant="outline" className="text-xs capitalize">
                    {currentFilters.side}
                  </Badge>
                )}
                {currentAdvancedFilters && Object.values(currentAdvancedFilters).some(v => v !== undefined && v !== 'all') && (
                  <Badge variant="outline" className="text-xs bg-amber-500/10 text-amber-500">
                    + Advanced
                  </Badge>
                )}
                <Badge variant="outline" className="text-xs">
                  {currentColumnPreset} preset
                </Badge>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!viewName.trim()}>
              <Check className="h-4 w-4 mr-1.5" />
              Save View
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default SavedViewsDropdown;

