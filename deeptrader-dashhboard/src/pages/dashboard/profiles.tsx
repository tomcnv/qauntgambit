import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { DashBar } from "../../components/DashBar";
import {
  Activity,
  Archive,
  ArrowUpDown,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Edit,
  ExternalLink,
  GitBranch,
  Layers,
  Library,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  Shield,
  Target,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { cn } from "../../lib/utils";
import { TooltipProvider, Tooltip, TooltipContent, TooltipTrigger } from "../../components/ui/tooltip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "../../components/ui/dropdown-menu";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import {
  useUserProfiles,
  useStrategyInstanceTemplates,
  useActivateUserProfile,
  useDeactivateUserProfile,
  usePromoteUserProfile,
  useCloneUserProfile,
  useArchiveUserProfile,
} from "../../lib/api/hooks";
import { StrategyInstance, UserProfile } from "../../lib/api/client";
import toast from "react-hot-toast";

// ============================================================================
// CONSTANTS
// ============================================================================

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const getEnvironmentStyle = (env: string) => {
  switch (env) {
    case "dev":
      return { bg: "bg-blue-500/10", border: "border-blue-500/30", text: "text-blue-400", label: "DEV" };
    case "paper":
      return { bg: "bg-amber-500/10", border: "border-amber-500/30", text: "text-amber-400", label: "PAPER" };
    case "live":
      return { bg: "bg-emerald-500/10", border: "border-emerald-500/30", text: "text-emerald-400", label: "LIVE" };
    default:
      return { bg: "bg-gray-500/10", border: "border-gray-500/30", text: "text-gray-400", label: env };
  }
};

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

// ============================================================================
// PROMOTION DIALOG
// ============================================================================

function PromotionDialog({
  isOpen,
  onClose,
  profile,
  onConfirm,
  isLoading,
}: {
  isOpen: boolean;
  onClose: () => void;
  profile: UserProfile | null;
  onConfirm: (notes: string) => void;
  isLoading: boolean;
}) {
  const [notes, setNotes] = useState("");
  const nextEnv = profile?.environment === "dev" ? "Paper" : profile?.environment === "paper" ? "Live" : null;
  const envStyle = nextEnv ? getEnvironmentStyle(nextEnv.toLowerCase()) : null;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="h-5 w-5" />
            Promote Profile
          </DialogTitle>
          <DialogDescription>
            Promote <span className="font-medium text-foreground">"{profile?.name}"</span> to {nextEnv}
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 space-y-4">
          <div className="flex items-center justify-center gap-4">
            <Badge className={cn("px-3 py-1", getEnvironmentStyle(profile?.environment || "dev").bg, getEnvironmentStyle(profile?.environment || "dev").border, getEnvironmentStyle(profile?.environment || "dev").text)}>
              {profile?.environment?.toUpperCase()}
            </Badge>
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
            {envStyle && (
              <Badge className={cn("px-3 py-1", envStyle.bg, envStyle.border, envStyle.text)}>
                {nextEnv?.toUpperCase()}
              </Badge>
            )}
          </div>

          {profile?.environment === "paper" && (
            <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
              <div className="flex items-start gap-2">
                <Shield className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-amber-500 text-sm">Live Trading Warning</p>
                  <p className="text-xs text-amber-500/80 mt-0.5">Real funds will be used.</p>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label className="text-xs">Notes (optional)</Label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why are you promoting this profile?"
              className="w-full min-h-[60px] px-3 py-2 text-sm rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button 
            size="sm"
            onClick={() => { onConfirm(notes); setNotes(""); }} 
            disabled={isLoading}
            className={profile?.environment === "paper" ? "bg-emerald-600 hover:bg-emerald-700" : ""}
          >
            {isLoading && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
            Promote
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="text-xs leading-5 p-3 rounded-lg border border-border bg-muted/30 overflow-x-auto">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function ProfileSettingsDrawer({
  profile,
  isOpen,
  onClose,
}: {
  profile: UserProfile | null;
  isOpen: boolean;
  onClose: () => void;
}) {
  if (!profile) return null;
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            {profile.name}
          </DialogTitle>
          <DialogDescription>
            {profile.is_system_template ? "Core profile template (read-only)" : "User profile configuration"}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Strategy Composition</h3>
            <JsonBlock value={profile.strategy_composition} />
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Risk Config</h3>
            <JsonBlock value={profile.risk_config} />
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Conditions</h3>
            <JsonBlock value={profile.conditions} />
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Lifecycle</h3>
            <JsonBlock value={profile.lifecycle} />
          </div>
          <div className="space-y-2 lg:col-span-2">
            <h3 className="text-sm font-semibold">Execution</h3>
            <JsonBlock value={profile.execution} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function StrategySettingsDrawer({
  strategy,
  isOpen,
  onClose,
}: {
  strategy: StrategyInstance | null;
  isOpen: boolean;
  onClose: () => void;
}) {
  if (!strategy) return null;
  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BookOpen className="h-5 w-5" />
            {strategy.name}
          </DialogTitle>
          <DialogDescription>
            Core strategy template settings (read-only)
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">
            Template: <span className="font-mono text-foreground">{strategy.template_id}</span> · Version: <span className="font-mono text-foreground">v{strategy.version}</span>
          </div>
          <JsonBlock value={strategy.params} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// TABLE HEADER
// ============================================================================

function TableHeader({
  children,
  sortable,
  sorted,
  direction,
  onClick,
  className,
}: {
  children: React.ReactNode;
  sortable?: boolean;
  sorted?: boolean;
  direction?: "asc" | "desc";
  onClick?: () => void;
  className?: string;
}) {
  return (
    <th
      className={cn(
        "text-left text-xs font-medium text-muted-foreground uppercase tracking-wider px-4 py-3",
        sortable && "cursor-pointer hover:text-foreground select-none",
        className
      )}
      onClick={sortable ? onClick : undefined}
    >
      <div className="flex items-center gap-1">
        {children}
        {sortable && (
          <ArrowUpDown className={cn("h-3 w-3", sorted ? "text-foreground" : "text-muted-foreground/50")} />
        )}
      </div>
    </th>
  );
}

// ============================================================================
// PAGINATION
// ============================================================================

function Pagination({
  currentPage,
  totalPages,
  pageSize,
  totalItems,
  onPageChange,
  onPageSizeChange,
}: {
  currentPage: number;
  totalPages: number;
  pageSize: number;
  totalItems: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const startItem = (currentPage - 1) * pageSize + 1;
  const endItem = Math.min(currentPage * pageSize, totalItems);

  return (
    <div className="flex items-center justify-between px-4 py-3 bg-muted/30 rounded-b-lg">
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground whitespace-nowrap">Show</span>
        <Select
          value={pageSize.toString()}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          options={PAGE_SIZE_OPTIONS.map((size) => ({ value: size.toString(), label: size.toString() }))}
        />
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {totalItems === 0 ? "No results" : `${startItem}–${endItem} of ${totalItems}`}
        </span>
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        {totalPages > 0 && Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
          let pageNum: number;
          if (totalPages <= 5) {
            pageNum = i + 1;
          } else if (currentPage <= 3) {
            pageNum = i + 1;
          } else if (currentPage >= totalPages - 2) {
            pageNum = totalPages - 4 + i;
          } else {
            pageNum = currentPage - 2 + i;
          }
          return (
            <Button
              key={pageNum}
              variant={currentPage === pageNum ? "default" : "ghost"}
              size="sm"
              className="h-8 w-8 p-0"
              onClick={() => onPageChange(pageNum)}
            >
              {pageNum}
            </Button>
          );
        })}
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages || totalPages === 0}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ============================================================================
// TEMPLATE TABLE
// ============================================================================

function TemplateTable({
  templates,
  onClone,
  onViewSettings,
  isCloning,
  cloningId,
  selectedIds,
  onToggleSelect,
  onSelectAll,
}: {
  templates: UserProfile[];
  onClone: (profile: UserProfile) => void;
  onViewSettings: (profile: UserProfile) => void;
  isCloning: boolean;
  cloningId: string | null;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: () => void;
}) {
  const allSelected = templates.length > 0 && templates.every((t) => selectedIds.has(t.id));
  const someSelected = templates.some((t) => selectedIds.has(t.id));

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <table className="w-full">
        <thead className="bg-muted/50">
          <tr>
            <th className="w-10 px-4 py-3">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                onChange={onSelectAll}
                className="rounded border-border"
              />
            </th>
            <TableHeader className="min-w-[200px]">Name</TableHeader>
            <TableHeader>Strategies</TableHeader>
            <TableHeader>Risk</TableHeader>
            <TableHeader>Leverage</TableHeader>
            <TableHeader className="w-[180px]">Actions</TableHeader>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {templates.map((profile) => {
            const strategyCount = profile.strategy_composition?.length || 0;
            const isSelected = selectedIds.has(profile.id);
            const isThisCloning = isCloning && cloningId === profile.id;

            return (
              <tr 
                key={profile.id} 
                className={cn(
                  "hover:bg-muted/30 transition-colors",
                  isSelected && "bg-primary/5"
                )}
              >
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleSelect(profile.id)}
                    className="rounded border-border"
                  />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div>
                      <div className="font-medium text-sm">{profile.name}</div>
                      <div className="text-xs text-muted-foreground line-clamp-1">
                        {profile.description || "Pre-configured trading profile"}
                      </div>
                    </div>
                    <Badge className="text-[9px] px-1.5 py-0 h-4 bg-purple-500/15 text-purple-400 border-purple-500/30">
                      TEMPLATE
                    </Badge>
                  </div>
                </td>
                <td className="px-4 py-3 text-sm">{strategyCount}</td>
                <td className="px-4 py-3 text-sm">{profile.risk_config?.risk_per_trade_pct || 1}%</td>
                <td className="px-4 py-3 text-sm">{profile.risk_config?.max_leverage || 2}x</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => onViewSettings(profile)}>
                      <Settings className="h-3 w-3 mr-1" />
                      View
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onClone(profile)}
                      disabled={isThisCloning}
                    >
                      {isThisCloning ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <>
                          <Copy className="h-3 w-3 mr-1" />
                          Clone
                        </>
                      )}
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {templates.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <Library className="h-8 w-8 mb-2 opacity-30" />
          <p className="text-sm">No templates found</p>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// USER PROFILE TABLE
// ============================================================================

function UserProfileTable({
  profiles,
  onViewSettings,
  onActivate,
  onDeactivate,
  onPromote,
  onClone,
  onArchive,
  onEdit,
  isActivating,
  activatingId,
  selectedIds,
  onToggleSelect,
  onSelectAll,
}: {
  profiles: UserProfile[];
  onViewSettings: (profile: UserProfile) => void;
  onActivate: (profile: UserProfile) => void;
  onDeactivate: (profile: UserProfile) => void;
  onPromote: (profile: UserProfile) => void;
  onClone: (profile: UserProfile) => void;
  onArchive: (profile: UserProfile) => void;
  onEdit: (profile: UserProfile) => void;
  isActivating: boolean;
  activatingId: string | null;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: () => void;
}) {
  const allSelected = profiles.length > 0 && profiles.every((p) => selectedIds.has(p.id));
  const someSelected = profiles.some((p) => selectedIds.has(p.id));

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <table className="w-full">
        <thead className="bg-muted/50">
          <tr>
            <th className="w-10 px-4 py-3">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                onChange={onSelectAll}
                className="rounded border-border"
              />
            </th>
            <TableHeader className="min-w-[200px]">Name</TableHeader>
            <TableHeader>Environment</TableHeader>
            <TableHeader>Status</TableHeader>
            <TableHeader>Strategies</TableHeader>
            <TableHeader>Risk</TableHeader>
            <TableHeader>Version</TableHeader>
            <TableHeader>Updated</TableHeader>
            <TableHeader className="w-[140px]">Actions</TableHeader>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {profiles.map((profile) => {
            const envStyle = getEnvironmentStyle(profile.environment);
            const strategyCount = profile.strategy_composition?.length || 0;
            const isSelected = selectedIds.has(profile.id);
            const isThisActivating = isActivating && activatingId === profile.id;
            const canPromote = profile.environment !== "live" && profile.status !== "archived";
            const nextEnv = profile.environment === "dev" ? "Paper" : profile.environment === "paper" ? "Live" : null;

            return (
              <tr 
                key={profile.id} 
                className={cn(
                  "hover:bg-muted/30 transition-colors",
                  isSelected && "bg-primary/5"
                )}
              >
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleSelect(profile.id)}
                    className="rounded border-border"
                  />
                </td>
                <td className="px-4 py-3">
                  <div>
                    <div className="font-medium text-sm">{profile.name}</div>
                    <div className="text-xs text-muted-foreground line-clamp-1">
                      {profile.description || "No description"}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge className={cn("text-[10px] px-2 py-0.5", envStyle.bg, envStyle.border, envStyle.text)}>
                    {envStyle.label}
                  </Badge>
                </td>
                <td className="px-4 py-3">
                  {profile.is_active ? (
                    <Badge className="text-[10px] px-2 py-0.5 bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
                      ACTIVE
                    </Badge>
                  ) : profile.status === "archived" ? (
                    <Badge className="text-[10px] px-2 py-0.5 bg-gray-500/15 text-gray-400 border-gray-500/30">
                      ARCHIVED
                    </Badge>
                  ) : (
                    <span className="text-sm text-muted-foreground">Inactive</span>
                  )}
                </td>
                <td className="px-4 py-3 text-sm">{strategyCount}</td>
                <td className="px-4 py-3 text-sm">{profile.risk_config?.risk_per_trade_pct || 1}%</td>
                <td className="px-4 py-3 text-sm font-mono">v{profile.version}</td>
                <td className="px-4 py-3 text-sm text-muted-foreground">{formatDate(profile.updated_at)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant={profile.is_active ? "default" : "outline"}
                            size="sm"
                            className={cn("h-7 w-7 p-0", profile.is_active && "bg-emerald-600 hover:bg-emerald-700")}
                            onClick={() => profile.is_active ? onDeactivate(profile) : onActivate(profile)}
                            disabled={isThisActivating || profile.status === "archived"}
                          >
                            {isThisActivating ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Activity className="h-3 w-3" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>{profile.is_active ? "Deactivate" : "Activate"}</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    
                    {canPromote && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button 
                              variant="outline" 
                              size="sm" 
                              className={cn(
                                "h-7 px-2 gap-1",
                                profile.environment === "paper" 
                                  ? "text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 border-emerald-500/30" 
                                  : "text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 border-amber-500/30"
                              )}
                              onClick={() => onPromote(profile)}
                            >
                              <GitBranch className="h-3 w-3" />
                              <span className="text-xs">{nextEnv}</span>
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Promote to {nextEnv}</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                    
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="outline" size="sm" className="h-7 w-7 p-0" onClick={() => onViewSettings(profile)}>
                            <BookOpen className="h-3 w-3" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>View Settings</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>

                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="outline" size="sm" className="h-7 w-7 p-0" onClick={() => onEdit(profile)}>
                            <Settings className="h-3 w-3" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Configure</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-7 w-7 p-0">
                          <MoreHorizontal className="h-3 w-3" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => onEdit(profile)}>
                          <Edit className="h-3 w-3 mr-2" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => onClone(profile)}>
                          <Copy className="h-3 w-3 mr-2" />
                          Clone
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        {profile.status !== "archived" && (
                          <DropdownMenuItem onClick={() => onArchive(profile)} className="text-amber-500">
                            <Archive className="h-3 w-3 mr-2" />
                            Archive
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {profiles.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <Layers className="h-8 w-8 mb-2 opacity-30" />
          <p className="text-sm">No profiles found</p>
        </div>
      )}
    </div>
  );
}

function CoreStrategiesTable({
  strategies,
  onViewSettings,
}: {
  strategies: StrategyInstance[];
  onViewSettings: (strategy: StrategyInstance) => void;
}) {
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <table className="w-full">
        <thead className="bg-muted/50">
          <tr>
            <TableHeader className="min-w-[260px]">Name</TableHeader>
            <TableHeader>Template ID</TableHeader>
            <TableHeader>Version</TableHeader>
            <TableHeader>Status</TableHeader>
            <TableHeader>Params</TableHeader>
            <TableHeader className="w-[120px]">Actions</TableHeader>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {strategies.map((strategy) => (
            <tr key={strategy.id} className="hover:bg-muted/30 transition-colors">
              <td className="px-4 py-3">
                <div className="font-medium text-sm">{strategy.name}</div>
                <div className="text-xs text-muted-foreground line-clamp-1">{strategy.description || "No description"}</div>
              </td>
              <td className="px-4 py-3 text-sm font-mono">{strategy.template_id}</td>
              <td className="px-4 py-3 text-sm font-mono">v{strategy.version}</td>
              <td className="px-4 py-3 text-sm">{strategy.status}</td>
              <td className="px-4 py-3 text-sm">{Object.keys(strategy.params || {}).length}</td>
              <td className="px-4 py-3">
                <Button variant="outline" size="sm" onClick={() => onViewSettings(strategy)}>
                  <Settings className="h-3 w-3 mr-1" />
                  View
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {strategies.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <BookOpen className="h-8 w-8 mb-2 opacity-30" />
          <p className="text-sm">No core strategies found</p>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// BULK ACTION BAR (Floating)
// ============================================================================

function BulkActionBar({
  selectedCount,
  onClearSelection,
  onBulkClone,
  onBulkArchive,
  onBulkActivate,
  onBulkDeactivate,
  onBulkPromote,
  canPromoteCount,
  isTemplate,
}: {
  selectedCount: number;
  onClearSelection: () => void;
  onBulkClone: () => void;
  onBulkArchive?: () => void;
  onBulkActivate?: () => void;
  onBulkDeactivate?: () => void;
  onBulkPromote?: () => void;
  canPromoteCount?: number;
  isTemplate: boolean;
}) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-4 fade-in duration-200">
      <div className="flex items-center gap-2 px-4 py-2.5 rounded-full bg-foreground text-background shadow-2xl">
        <div className="flex items-center gap-2 pr-2 border-r border-background/20">
          <div className="h-6 w-6 rounded-full bg-primary flex items-center justify-center text-xs font-bold text-primary-foreground">
            {selectedCount}
          </div>
          <span className="text-sm font-medium">selected</span>
        </div>
        <Button 
          size="sm" 
          variant="ghost" 
          className="h-8 text-background hover:bg-background/10 hover:text-background"
          onClick={onBulkClone}
        >
          <Copy className="h-3.5 w-3.5 mr-1.5" />
          Clone
        </Button>
        {!isTemplate && (
          <>
            <Button 
              size="sm" 
              variant="ghost" 
              className="h-8 text-background hover:bg-background/10 hover:text-background"
              onClick={onBulkActivate}
            >
              <Activity className="h-3.5 w-3.5 mr-1.5" />
              Activate
            </Button>
            <Button 
              size="sm" 
              variant="ghost" 
              className="h-8 text-background hover:bg-background/10 hover:text-background"
              onClick={onBulkDeactivate}
            >
              Deactivate
            </Button>
            {(canPromoteCount || 0) > 0 && (
              <Button 
                size="sm" 
                variant="ghost" 
                className="h-8 text-amber-400 hover:bg-background/10 hover:text-amber-300"
                onClick={onBulkPromote}
              >
                <GitBranch className="h-3.5 w-3.5 mr-1.5" />
                Promote ({canPromoteCount})
              </Button>
            )}
            <Button 
              size="sm" 
              variant="ghost" 
              className="h-8 text-red-400 hover:bg-background/10 hover:text-red-400"
              onClick={onBulkArchive}
            >
              <Archive className="h-3.5 w-3.5 mr-1.5" />
              Archive
            </Button>
          </>
        )}
        <div className="pl-2 border-l border-background/20">
          <Button 
            size="sm" 
            variant="ghost" 
            className="h-8 w-8 p-0 text-background/60 hover:bg-background/10 hover:text-background"
            onClick={onClearSelection}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function ProfilesPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<"templates" | "my-profiles" | "core-strategies">("templates");
  const [envFilter, setEnvFilter] = useState<"all" | "dev" | "paper" | "live">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"updated" | "name" | "active">("updated");
  
  // Pagination state
  const [templatePage, setTemplatePage] = useState(1);
  const [profilePage, setProfilePage] = useState(1);
  const [templatePageSize, setTemplatePageSize] = useState(10);
  const [profilePageSize, setProfilePageSize] = useState(10);
  
  // Selection state
  const [selectedTemplates, setSelectedTemplates] = useState<Set<string>>(new Set());
  const [selectedProfiles, setSelectedProfiles] = useState<Set<string>>(new Set());
  
  // Promotion dialog state
  const [promoteDialogOpen, setPromoteDialogOpen] = useState(false);
  const [profileToPromote, setProfileToPromote] = useState<UserProfile | null>(null);
  const [profileSettingsOpen, setProfileSettingsOpen] = useState(false);
  const [selectedProfileForSettings, setSelectedProfileForSettings] = useState<UserProfile | null>(null);
  const [strategySettingsOpen, setStrategySettingsOpen] = useState(false);
  const [selectedStrategyForSettings, setSelectedStrategyForSettings] = useState<StrategyInstance | null>(null);

  // API hooks
  const { data: profilesData, isLoading: loadingProfiles, refetch } = useUserProfiles();
  const { data: strategyTemplatesData, isLoading: loadingStrategyTemplates } = useStrategyInstanceTemplates();

  const activateMutation = useActivateUserProfile();
  const deactivateMutation = useDeactivateUserProfile();
  const promoteMutation = usePromoteUserProfile();
  const cloneMutation = useCloneUserProfile();
  const archiveMutation = useArchiveUserProfile();

  const allProfiles = profilesData?.profiles || [];
  const coreStrategies = strategyTemplatesData?.templates?.filter((s) => s.is_system_template) || [];

  // Separate templates and user profiles
  const { templates, userProfiles } = useMemo(() => {
    const templates = allProfiles.filter((p: any) => p.is_system_template);
    const userProfiles = allProfiles.filter((p: any) => !p.is_system_template);
    return { templates, userProfiles };
  }, [allProfiles]);

  // Filter templates
  const filteredTemplates = useMemo(() => {
    if (!searchQuery) return templates;
    const q = searchQuery.toLowerCase();
    return templates.filter((p) => 
      p.name.toLowerCase().includes(q) || 
      (p.description || "").toLowerCase().includes(q)
    );
  }, [templates, searchQuery]);

  // Filter and sort user profiles
  const filteredUserProfiles = useMemo(() => {
    let result = [...userProfiles];
    if (envFilter !== "all") result = result.filter((p) => p.environment === envFilter);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter((p) => p.name.toLowerCase().includes(q) || (p.description || "").toLowerCase().includes(q));
    }
    if (statusFilter !== "all") {
      if (statusFilter === "active") result = result.filter((p) => p.is_active);
      else result = result.filter((p) => p.status === statusFilter);
    }
    result.sort((a, b) => {
      switch (sortBy) {
        case "name": return a.name.localeCompare(b.name);
        case "active": return Number(b.is_active) - Number(a.is_active);
        default: return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      }
    });
    return result;
  }, [userProfiles, envFilter, searchQuery, statusFilter, sortBy]);

  const filteredCoreStrategies = useMemo(() => {
    if (!searchQuery) return coreStrategies;
    const q = searchQuery.toLowerCase();
    return coreStrategies.filter((s) =>
      s.name.toLowerCase().includes(q) ||
      (s.description || "").toLowerCase().includes(q) ||
      s.template_id.toLowerCase().includes(q)
    );
  }, [coreStrategies, searchQuery]);

  // Paginated data
  const paginatedTemplates = useMemo(() => {
    const start = (templatePage - 1) * templatePageSize;
    return filteredTemplates.slice(start, start + templatePageSize);
  }, [filteredTemplates, templatePage, templatePageSize]);

  const paginatedProfiles = useMemo(() => {
    const start = (profilePage - 1) * profilePageSize;
    return filteredUserProfiles.slice(start, start + profilePageSize);
  }, [filteredUserProfiles, profilePage, profilePageSize]);

  const templateTotalPages = Math.ceil(filteredTemplates.length / templatePageSize);
  const profileTotalPages = Math.ceil(filteredUserProfiles.length / profilePageSize);

  // Stats
  const stats = useMemo(() => ({
    templates: templates.length,
    coreStrategies: coreStrategies.length,
    total: userProfiles.length,
    active: userProfiles.filter((p) => p.is_active).length,
    dev: userProfiles.filter((p) => p.environment === "dev").length,
    paper: userProfiles.filter((p) => p.environment === "paper").length,
    live: userProfiles.filter((p) => p.environment === "live").length,
  }), [templates, coreStrategies, userProfiles]);

  // Selection handlers
  const toggleTemplateSelection = (id: string) => {
    setSelectedTemplates(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleProfileSelection = (id: string) => {
    setSelectedProfiles(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllTemplates = () => {
    if (paginatedTemplates.every(t => selectedTemplates.has(t.id))) {
      setSelectedTemplates(new Set());
    } else {
      setSelectedTemplates(new Set(paginatedTemplates.map(t => t.id)));
    }
  };

  const selectAllProfiles = () => {
    if (paginatedProfiles.every(p => selectedProfiles.has(p.id))) {
      setSelectedProfiles(new Set());
    } else {
      setSelectedProfiles(new Set(paginatedProfiles.map(p => p.id)));
    }
  };

  const clearSelection = () => {
    setSelectedTemplates(new Set());
    setSelectedProfiles(new Set());
  };

  // Action handlers
  const handleActivate = (profile: UserProfile) => {
    activateMutation.mutate(profile.id, {
      onSuccess: () => { toast.success(`"${profile.name}" activated`); refetch(); },
      onError: (err: any) => toast.error(err?.response?.data?.message || "Failed to activate"),
    });
  };

  const handleDeactivate = (profile: UserProfile) => {
    deactivateMutation.mutate(profile.id, {
      onSuccess: () => { toast.success(`"${profile.name}" deactivated`); refetch(); },
      onError: (err: any) => toast.error(err?.response?.data?.message || "Failed to deactivate"),
    });
  };

  const handlePromote = (notes: string) => {
    if (!profileToPromote) return;
    promoteMutation.mutate(
      { id: profileToPromote.id, notes },
      {
        onSuccess: (data) => {
          toast.success(data.message);
          setPromoteDialogOpen(false);
          setProfileToPromote(null);
          refetch();
        },
        onError: (err: any) => toast.error(err?.response?.data?.message || "Failed to promote"),
      }
    );
  };

  const handleArchive = (profile: UserProfile) => {
    archiveMutation.mutate(profile.id, {
      onSuccess: () => { toast.success(`"${profile.name}" archived`); refetch(); },
      onError: (err: any) => toast.error(err?.response?.data?.message || "Failed to archive"),
    });
  };

  const handleClone = (profile: UserProfile) => {
    cloneMutation.mutate(
      { id: profile.id },
      {
        onSuccess: (data) => {
          toast.success(`Cloned as "${data.profile.name}"`);
          setActiveTab("my-profiles");
          refetch();
        },
        onError: (err: any) => toast.error(err?.response?.data?.message || "Failed to clone"),
      }
    );
  };

  const handleViewProfileSettings = (profile: UserProfile) => {
    setSelectedProfileForSettings(profile);
    setProfileSettingsOpen(true);
  };

  const handleViewStrategySettings = (strategy: StrategyInstance) => {
    setSelectedStrategyForSettings(strategy);
    setStrategySettingsOpen(true);
  };

  // Bulk action handlers
  const handleBulkClone = () => {
    const ids = activeTab === "templates" ? selectedTemplates : selectedProfiles;
    const profiles = activeTab === "templates" ? templates : userProfiles;
    ids.forEach(id => {
      const profile = profiles.find(p => p.id === id);
      if (profile) handleClone(profile);
    });
    clearSelection();
  };

  const handleBulkActivate = () => {
    selectedProfiles.forEach(id => {
      const profile = userProfiles.find(p => p.id === id);
      if (profile && !profile.is_active) handleActivate(profile);
    });
    clearSelection();
  };

  const handleBulkDeactivate = () => {
    selectedProfiles.forEach(id => {
      const profile = userProfiles.find(p => p.id === id);
      if (profile && profile.is_active) handleDeactivate(profile);
    });
    clearSelection();
  };

  const handleBulkArchive = () => {
    selectedProfiles.forEach(id => {
      const profile = userProfiles.find(p => p.id === id);
      if (profile && profile.status !== "archived") handleArchive(profile);
    });
    clearSelection();
  };

  const handleBulkPromote = () => {
    // Get all promotable profiles
    const promotableProfiles = userProfiles.filter(p =>
      selectedProfiles.has(p.id) &&
      p.environment !== "live" &&
      p.status !== "archived"
    );
    
    if (promotableProfiles.length === 0) return;
    
    // Promote all selected profiles directly
    let successCount = 0;
    let failCount = 0;
    
    promotableProfiles.forEach(profile => {
      const nextEnv = profile.environment === "dev" ? "Paper" : "Live";
      promoteMutation.mutate(
        { id: profile.id, notes: `Bulk promotion to ${nextEnv}` },
        {
          onSuccess: () => {
            successCount++;
            if (successCount + failCount === promotableProfiles.length) {
              toast.success(`Promoted ${successCount} profile(s) successfully`);
              refetch();
            }
          },
          onError: (err: any) => {
            failCount++;
            toast.error(`Failed to promote "${profile.name}": ${err?.response?.data?.message || "Unknown error"}`);
            if (successCount + failCount === promotableProfiles.length) {
              refetch();
            }
          },
        }
      );
    });
    
    clearSelection();
  };

  // Count how many selected profiles can be promoted
  const canPromoteCount = useMemo(() => {
    return userProfiles.filter(p => 
      selectedProfiles.has(p.id) && 
      p.environment !== "live" && 
      p.status !== "archived"
    ).length;
  }, [userProfiles, selectedProfiles]);

  const currentSelection = activeTab === "templates" ? selectedTemplates.size : activeTab === "my-profiles" ? selectedProfiles.size : 0;

  // Reset page when filters change
  const resetTemplatePage = () => setTemplatePage(1);
  const resetProfilePage = () => setProfilePage(1);

  return (
    <>
      <DashBar />
      <TooltipProvider>
        <div className="p-6 space-y-4 max-w-[1600px] mx-auto w-full">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold tracking-tight">Trading Profiles</h1>
              <p className="text-sm text-muted-foreground">
                Configure trading strategies, risk parameters, and market conditions
              </p>
            </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate("/dashboard/strategies")}>
              <Zap className="h-4 w-4 mr-1" />
              Strategies
            </Button>
            <Button size="sm" onClick={() => navigate("/dashboard/profile-editor")}>
              <Plus className="h-4 w-4 mr-1" />
              New Profile
            </Button>
          </div>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-3 md:grid-cols-7 gap-3">
          <div className="flex items-center gap-2 p-3 rounded-lg border border-purple-500/20 bg-card">
            <Library className="h-4 w-4 text-purple-400" />
            <div>
              <div className="text-lg font-bold text-purple-400">{stats.templates}</div>
              <div className="text-[10px] uppercase text-muted-foreground">Core Profiles</div>
            </div>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-indigo-500/20 bg-card">
            <BookOpen className="h-4 w-4 text-indigo-400" />
            <div>
              <div className="text-lg font-bold text-indigo-400">{stats.coreStrategies}</div>
              <div className="text-[10px] uppercase text-muted-foreground">Core Strategies</div>
            </div>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-border bg-card">
            <Layers className="h-4 w-4 text-muted-foreground" />
            <div>
              <div className="text-lg font-bold">{stats.total}</div>
              <div className="text-[10px] uppercase text-muted-foreground">My Profiles</div>
            </div>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-emerald-500/20 bg-card">
            <Activity className="h-4 w-4 text-emerald-400" />
            <div>
              <div className="text-lg font-bold text-emerald-400">{stats.active}</div>
              <div className="text-[10px] uppercase text-muted-foreground">Active</div>
            </div>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-blue-500/20 bg-card">
            <Settings className="h-4 w-4 text-blue-400" />
            <div>
              <div className="text-lg font-bold text-blue-400">{stats.dev}</div>
              <div className="text-[10px] uppercase text-muted-foreground">Dev</div>
            </div>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-amber-500/20 bg-card">
            <Target className="h-4 w-4 text-amber-400" />
            <div>
              <div className="text-lg font-bold text-amber-400">{stats.paper}</div>
              <div className="text-[10px] uppercase text-muted-foreground">Paper</div>
            </div>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-emerald-500/20 bg-card">
            <TrendingUp className="h-4 w-4 text-emerald-400" />
            <div>
              <div className="text-lg font-bold text-emerald-400">{stats.live}</div>
              <div className="text-[10px] uppercase text-muted-foreground">Live</div>
            </div>
          </div>
        </div>

        {/* Main Tabs */}
        <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v as typeof activeTab); clearSelection(); }}>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
            <TabsList className="h-9">
              <TabsTrigger value="templates" className="gap-1.5 px-3 text-sm">
                <Library className="h-3.5 w-3.5" />
                Core Profiles
                <span className="text-[10px] text-purple-400 font-medium">{stats.templates}</span>
              </TabsTrigger>
              <TabsTrigger value="core-strategies" className="gap-1.5 px-3 text-sm">
                <BookOpen className="h-3.5 w-3.5" />
                Core Strategies
                <span className="text-[10px] text-indigo-400 font-medium">{stats.coreStrategies}</span>
              </TabsTrigger>
              <TabsTrigger value="my-profiles" className="gap-1.5 px-3 text-sm">
                <Layers className="h-3.5 w-3.5" />
                My Profiles
                <span className="text-[10px] text-muted-foreground font-medium">{stats.total}</span>
              </TabsTrigger>
            </TabsList>

            {/* Filters */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search..."
                  value={searchQuery}
                  onChange={(e) => { setSearchQuery(e.target.value); activeTab === "templates" ? resetTemplatePage() : resetProfilePage(); }}
                  className="pl-8 h-9 w-[200px] text-sm"
                />
              </div>
              
              {activeTab === "my-profiles" && (
                <>
                  <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-muted border border-border">
                    {(["all", "dev", "paper", "live"] as const).map((env) => {
                      const style = env === "all" ? null : getEnvironmentStyle(env);
                      return (
                        <button
                          key={env}
                          onClick={() => { setEnvFilter(env); resetProfilePage(); }}
                          className={cn(
                            "px-2 py-1 rounded text-xs font-medium transition-colors",
                            envFilter === env
                              ? style ? cn(style.bg, style.text) : "bg-background text-foreground shadow-sm"
                              : "text-muted-foreground hover:text-foreground"
                          )}
                        >
                          {env === "all" ? "All" : style?.label}
                        </button>
                      );
                    })}
                  </div>

                  <Select
                    value={statusFilter}
                    onChange={(e) => { setStatusFilter(e.target.value); resetProfilePage(); }}
                    options={[
                      { value: "all", label: "All Status" },
                      { value: "active", label: "Active" },
                      { value: "draft", label: "Draft" },
                      { value: "archived", label: "Archived" },
                    ]}
                  />

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" size="sm" className="h-9">
                        <ArrowUpDown className="h-3 w-3 mr-1" />
                        Sort
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                      <DropdownMenuItem onClick={() => setSortBy("updated")}>Recently Updated</DropdownMenuItem>
                      <DropdownMenuItem onClick={() => setSortBy("name")}>Name</DropdownMenuItem>
                      <DropdownMenuItem onClick={() => setSortBy("active")}>Active First</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </>
              )}
            </div>
          </div>

          {/* Templates Tab */}
          <TabsContent value="templates" className="mt-0">
            {loadingProfiles ? (
              <div className="flex items-center justify-center py-12 border border-border rounded-lg">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="border border-border rounded-lg overflow-hidden">
                <TemplateTable
                  templates={paginatedTemplates}
                  onClone={handleClone}
                  onViewSettings={handleViewProfileSettings}
                  isCloning={cloneMutation.isPending}
                  cloningId={(cloneMutation.variables as any)?.id || null}
                  selectedIds={selectedTemplates}
                  onToggleSelect={toggleTemplateSelection}
                  onSelectAll={selectAllTemplates}
                />
                {filteredTemplates.length > 0 && (
                  <Pagination
                    currentPage={templatePage}
                    totalPages={templateTotalPages}
                    pageSize={templatePageSize}
                    totalItems={filteredTemplates.length}
                    onPageChange={setTemplatePage}
                    onPageSizeChange={(size) => { setTemplatePageSize(size); setTemplatePage(1); }}
                  />
                )}
              </div>
            )}
          </TabsContent>

          <TabsContent value="core-strategies" className="mt-0">
            {loadingStrategyTemplates ? (
              <div className="flex items-center justify-center py-12 border border-border rounded-lg">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <CoreStrategiesTable
                strategies={filteredCoreStrategies}
                onViewSettings={handleViewStrategySettings}
              />
            )}
          </TabsContent>

          {/* My Profiles Tab */}
          <TabsContent value="my-profiles" className="mt-0">
            {loadingProfiles ? (
              <div className="flex items-center justify-center py-12 border border-border rounded-lg">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="border border-border rounded-lg overflow-hidden">
                <UserProfileTable
                  profiles={paginatedProfiles}
                  onViewSettings={handleViewProfileSettings}
                  onActivate={handleActivate}
                  onDeactivate={handleDeactivate}
                  onPromote={(p) => { setProfileToPromote(p); setPromoteDialogOpen(true); }}
                  onClone={handleClone}
                  onArchive={handleArchive}
                  onEdit={(p) => navigate(`/dashboard/profile-editor?id=${p.id}`)}
                  isActivating={activateMutation.isPending || deactivateMutation.isPending}
                  activatingId={activateMutation.variables as string || deactivateMutation.variables as string || null}
                  selectedIds={selectedProfiles}
                  onToggleSelect={toggleProfileSelection}
                  onSelectAll={selectAllProfiles}
                />
                {filteredUserProfiles.length > 0 && (
                  <Pagination
                    currentPage={profilePage}
                    totalPages={profileTotalPages}
                    pageSize={profilePageSize}
                    totalItems={filteredUserProfiles.length}
                    onPageChange={setProfilePage}
                    onPageSizeChange={(size) => { setProfilePageSize(size); setProfilePage(1); }}
                  />
                )}
              </div>
            )}
          </TabsContent>
        </Tabs>

        {/* Promotion Dialog */}
        <PromotionDialog
          isOpen={promoteDialogOpen}
          onClose={() => { setPromoteDialogOpen(false); setProfileToPromote(null); }}
          profile={profileToPromote}
          onConfirm={handlePromote}
          isLoading={promoteMutation.isPending}
        />

        <ProfileSettingsDrawer
          profile={selectedProfileForSettings}
          isOpen={profileSettingsOpen}
          onClose={() => {
            setProfileSettingsOpen(false);
            setSelectedProfileForSettings(null);
          }}
        />

        <StrategySettingsDrawer
          strategy={selectedStrategyForSettings}
          isOpen={strategySettingsOpen}
          onClose={() => {
            setStrategySettingsOpen(false);
            setSelectedStrategyForSettings(null);
          }}
        />

        {/* Floating Bulk Action Bar */}
        {activeTab === "templates" ? (
          <BulkActionBar
            selectedCount={selectedTemplates.size}
            onClearSelection={clearSelection}
            onBulkClone={handleBulkClone}
            isTemplate={true}
          />
        ) : activeTab === "my-profiles" ? (
          <BulkActionBar
            selectedCount={selectedProfiles.size}
            onClearSelection={clearSelection}
            onBulkClone={handleBulkClone}
            onBulkArchive={handleBulkArchive}
            onBulkActivate={handleBulkActivate}
            onBulkDeactivate={handleBulkDeactivate}
            onBulkPromote={handleBulkPromote}
            canPromoteCount={canPromoteCount}
            isTemplate={false}
          />
          ) : null}
        </div>
      </TooltipProvider>
    </>
  );
}
