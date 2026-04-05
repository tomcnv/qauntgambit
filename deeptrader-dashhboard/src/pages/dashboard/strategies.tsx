import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ArrowRight,
  ArrowUpDown,
  BookOpen,
  Check,
  ChevronRight,
  Clock,
  Copy,
  Edit,
  ExternalLink,
  Layers,
  Loader2,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Tag,
  TrendingUp,
  X,
  Zap,
  AlertCircle,
  RotateCcw,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { cn } from "../../lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "../../components/ui/dropdown-menu";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import {
  useStrategyInstances,
  useStrategyInstanceTemplates,
  useCreateStrategyInstance,
  useUpdateStrategyInstance,
  useCloneStrategyInstance,
  useArchiveStrategyInstance,
  useRestoreStrategyInstance,
  useStrategyInstanceUsage,
} from "../../lib/api/hooks";
import { StrategyInstance } from "../../lib/api/client";
import toast from "react-hot-toast";

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

const getCategoryColor = (category: string) => {
  switch (category) {
    case "scalping":
      return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    case "trend_following":
      return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    case "mean_reversion":
      return "bg-amber-500/20 text-amber-400 border-amber-500/30";
    case "breakout":
      return "bg-purple-500/20 text-purple-400 border-purple-500/30";
    default:
      return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
};

const getStatusColor = (status: string) => {
  switch (status) {
    case "active":
      return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    case "deprecated":
      return "bg-amber-500/20 text-amber-400 border-amber-500/30";
    case "archived":
      return "bg-gray-500/20 text-gray-400 border-gray-500/30";
    default:
      return "bg-gray-500/20 text-gray-400 border-gray-500/30";
  }
};

// Helper to derive category from template_id
const deriveCategory = (templateId: string): string => {
  if (templateId.includes('reversion') || templateId.includes('fade') || templateId.includes('poc') || templateId.includes('vwap')) return 'mean_reversion';
  if (templateId.includes('breakout') || templateId.includes('expansion')) return 'breakout';
  if (templateId.includes('trend') || templateId.includes('momentum') || templateId.includes('pullback')) return 'trend_following';
  if (templateId.includes('scalp') || templateId.includes('grind') || templateId.includes('compression')) return 'scalping';
  return 'other';
};

// ============================================================================
// COMPONENTS
// ============================================================================

function StrategyInstanceDrawer({
  instance,
  isOpen,
  onClose,
  onClone,
  onArchive,
  onRestore,
}: {
  instance: StrategyInstance | null;
  isOpen: boolean;
  onClose: () => void;
  onClone: (instance: StrategyInstance) => void;
  onArchive: (instance: StrategyInstance) => void;
  onRestore: (instance: StrategyInstance) => void;
}) {
  const [activeTab, setActiveTab] = useState<"overview" | "params" | "usage">("overview");
  const { data: usageData, isLoading: loadingUsage } = useStrategyInstanceUsage(instance?.id || "");

  if (!instance) return null;

  const category = deriveCategory(instance.template_id);

  return (
    <Sheet open={isOpen} onOpenChange={onClose}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <SheetTitle>{instance.name}</SheetTitle>
            <Badge className={cn("text-[10px]", getStatusColor(instance.status))}>
              {instance.status.toUpperCase()}
            </Badge>
            {instance.is_system_template && (
              <Badge className="text-[10px] bg-purple-500/20 text-purple-400">
                TEMPLATE
              </Badge>
            )}
          </div>
          <SheetDescription>{instance.description || "No description"}</SheetDescription>
        </SheetHeader>

        {/* Tabs */}
        <div className="flex gap-1 mt-4 border-b border-border">
          {(["overview", "params", "usage"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-3 py-2 text-sm font-medium border-b-2 transition-colors capitalize",
                activeTab === tab
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="mt-4 space-y-4">
          {activeTab === "overview" && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Template</Label>
                  <div className="flex items-center gap-2 mt-1">
                    <Badge variant="outline" className={cn("text-xs", getCategoryColor(category))}>
                      {category.replace(/_/g, " ")}
                    </Badge>
                  </div>
                  <p className="text-sm mt-1">{instance.template_id.replace(/_/g, " ")}</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Version</Label>
                  <p className="text-sm mt-1">v{instance.version}</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Profiles Using</Label>
                  <p className="text-sm mt-1">{instance.usage_count || 0}</p>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Last Updated</Label>
                  <p className="text-sm mt-1">{new Date(instance.updated_at).toLocaleDateString()}</p>
                </div>
              </div>

              {instance.last_backtest_summary && (
                <div>
                  <Label className="text-xs text-muted-foreground">Last Backtest</Label>
                  <div className="mt-1 p-3 rounded-lg bg-muted/30 border border-border">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      {Object.entries(instance.last_backtest_summary).map(([key, value]) => (
                        <div key={key}>
                          <span className="text-muted-foreground">{key}: </span>
                          <span className="font-mono">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {activeTab === "params" && (
            <div className="space-y-3">
              {Object.keys(instance.params || {}).length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Settings className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">No parameters configured</p>
                </div>
              ) : (
                Object.entries(instance.params || {}).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted/30">
                    <div>
                      <p className="text-sm font-medium">{key.replace(/_/g, " ")}</p>
                      <p className="text-xs text-muted-foreground">Strategy parameter</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-mono">{String(value)}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {activeTab === "usage" && (
            <div className="space-y-3">
              {loadingUsage ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : usageData?.profiles?.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Layers className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">Not used by any profiles</p>
                  <Link to="/dashboard/profile-editor">
                    <Button variant="outline" size="sm" className="mt-4">
                      <Plus className="h-4 w-4 mr-2" />
                      Add to Profile
                    </Button>
                  </Link>
                </div>
              ) : (
                usageData?.profiles?.map((profile) => (
                  <Link
                    key={profile.id}
                    to={`/dashboard/profile-editor?id=${profile.id}`}
                    className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted/30 hover:bg-muted/50 transition-colors"
                  >
                    <div>
                      <p className="text-sm font-medium">{profile.name}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant="outline" className="text-[10px]">
                          {profile.environment}
                        </Badge>
                        {profile.is_active && (
                          <Badge className="text-[10px] bg-emerald-500/20 text-emerald-400">
                            Active
                          </Badge>
                        )}
                      </div>
                    </div>
                    <ExternalLink className="h-4 w-4 text-muted-foreground" />
                  </Link>
                ))
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2 mt-6 pt-4 border-t border-border">
          <Button variant="outline" size="sm" className="flex-1" onClick={() => onClone(instance)}>
            <Copy className="h-4 w-4 mr-2" />
            Clone
          </Button>
          {instance.status === "archived" ? (
            <Button variant="outline" size="sm" className="flex-1" onClick={() => onRestore(instance)}>
              <RotateCcw className="h-4 w-4 mr-2" />
              Restore
            </Button>
          ) : (
            <Button variant="outline" size="sm" className="flex-1" onClick={() => onArchive(instance)}>
              <Archive className="h-4 w-4 mr-2" />
              Archive
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function CreateInstanceDialog({
  isOpen,
  onClose,
  preselectedTemplate,
}: {
  isOpen: boolean;
  onClose: () => void;
  preselectedTemplate?: StrategyInstance | null;
}) {
  const [step, setStep] = useState<"template" | "details">(preselectedTemplate ? "details" : "template");
  const [selectedTemplate, setSelectedTemplate] = useState<StrategyInstance | null>(preselectedTemplate || null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  
  const createMutation = useCreateStrategyInstance();
  const { data: templatesData, isLoading: loadingTemplates } = useStrategyInstanceTemplates();
  const templates = templatesData?.templates || [];
  
  // Helper to get category
  const getCategory = (templateId: string) => {
    if (templateId.includes('reversion') || templateId.includes('fade') || templateId.includes('poc') || templateId.includes('vwap')) return 'mean_reversion';
    if (templateId.includes('breakout') || templateId.includes('expansion')) return 'breakout';
    if (templateId.includes('trend') || templateId.includes('momentum') || templateId.includes('pullback')) return 'trend_following';
    if (templateId.includes('scalp') || templateId.includes('grind') || templateId.includes('compression')) return 'scalping';
    return 'other';
  };

  const handleSelectTemplate = (template: StrategyInstance) => {
    setSelectedTemplate(template);
    setName(`${template.name} - Custom`);
    setDescription(template.description || "");
    setParams({ ...(template.params || {}) });
    setStep("details");
  };

  const handleCreate = () => {
    if (!selectedTemplate || !name.trim()) {
      toast.error("Name is required");
      return;
    }

    createMutation.mutate(
      {
        templateId: selectedTemplate.template_id,
        name: name.trim(),
        description: description || undefined,
        params,
      },
      {
        onSuccess: () => {
          toast.success("Strategy instance created");
          handleClose();
        },
        onError: (err: any) => {
          toast.error(err?.response?.data?.message || "Failed to create instance");
        },
      }
    );
  };

  const handleClose = () => {
    onClose();
    setStep("template");
    setSelectedTemplate(null);
    setName("");
    setDescription("");
    setParams({});
  };

  const filteredTemplates = useMemo(() => {
    return templates.filter((t) => {
      const matchesSearch = !searchQuery || 
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (t.description || "").toLowerCase().includes(searchQuery.toLowerCase());
      const category = getCategory(t.template_id);
      const matchesCategory = categoryFilter === "all" || category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [templates, searchQuery, categoryFilter]);

  const categories = useMemo(() => {
    const cats = new Set<string>();
    templates.forEach(t => cats.add(getCategory(t.template_id)));
    return [...cats];
  }, [templates]);

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {step === "template" ? "Select Strategy Template" : "Configure Strategy Instance"}
          </DialogTitle>
          <DialogDescription>
            {step === "template"
              ? "Choose a strategy template to create a customized instance"
              : `Creating instance from "${selectedTemplate?.name}"`}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto py-4">
          {step === "template" && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search templates..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9"
                  />
                </div>
                <Select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  options={[
                    { value: "all", label: "All Categories" },
                    ...categories.map((c) => ({ value: c, label: c.replace(/_/g, " ") })),
                  ]}
                  className="w-[160px]"
                />
              </div>

              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {loadingTemplates ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : (
                  filteredTemplates.map((template) => {
                    const category = getCategory(template.template_id);
                    return (
                      <button
                        key={template.id}
                        onClick={() => handleSelectTemplate(template)}
                        className="w-full p-4 rounded-lg border border-border hover:border-primary/50 hover:bg-muted/30 transition-colors text-left"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2">
                              <p className="font-medium">{template.name}</p>
                              <Badge className={cn("text-[10px]", getCategoryColor(category))}>
                                {category.replace(/_/g, " ")}
                              </Badge>
                            </div>
                            <p className="text-sm text-muted-foreground mt-1">{template.description || "No description"}</p>
                          </div>
                          <ChevronRight className="h-4 w-4 text-muted-foreground mt-1 flex-shrink-0" />
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {step === "details" && selectedTemplate && (
            <div className="space-y-4">
              <div className="p-3 rounded-lg border border-primary/30 bg-primary/5">
                <div className="flex items-center gap-2">
                  <Badge className={cn("text-[10px]", getCategoryColor(getCategory(selectedTemplate.template_id)))}>
                    {getCategory(selectedTemplate.template_id).replace(/_/g, " ")}
                  </Badge>
                  <span className="text-sm font-medium">{selectedTemplate.name}</span>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Instance Name *</Label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., POC Magnet - High Vol v1"
                />
              </div>

              <div className="space-y-2">
                <Label>Description</Label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe when this strategy instance should be used..."
                  className="w-full min-h-[80px] px-3 py-2 text-sm rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>

              <div className="space-y-2">
                <Label>Parameters</Label>
                <div className="space-y-2">
                  {Object.entries(params).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2">
                      <Label className="text-sm w-1/3">{key.replace(/_/g, " ")}</Label>
                      <Input
                        value={String(value)}
                        onChange={(e) => {
                          const newValue = isNaN(Number(e.target.value)) 
                            ? e.target.value === "true" ? true : e.target.value === "false" ? false : e.target.value
                            : Number(e.target.value);
                          setParams({ ...params, [key]: newValue });
                        }}
                        className="flex-1 font-mono text-sm"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => step === "template" ? handleClose() : setStep("template")}>
            {step === "template" ? "Cancel" : "Back"}
          </Button>
          {step === "details" && (
            <Button onClick={handleCreate} disabled={!name.trim() || createMutation.isPending}>
              {createMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Instance
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function StrategiesPage() {
  const [activeTab, setActiveTab] = useState<"instances" | "library">("library");
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("active");
  const [sortBy, setSortBy] = useState<"updated" | "name" | "usage">("updated");

  // Drawer/dialog states
  const [selectedInstance, setSelectedInstance] = useState<StrategyInstance | null>(null);
  const [instanceDrawerOpen, setInstanceDrawerOpen] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [preselectedTemplate, setPreselectedTemplate] = useState<StrategyInstance | null>(null);

  // API hooks - fetch system templates (library) and user instances separately
  const { data: templatesData, isLoading: loadingTemplates } = useStrategyInstanceTemplates();
  const { data: instancesData, isLoading: loadingInstances } = useStrategyInstances(
    statusFilter !== "all" ? { status: statusFilter, includeSystemTemplates: false } : { includeSystemTemplates: false }
  );
  const cloneMutation = useCloneStrategyInstance();
  const archiveMutation = useArchiveStrategyInstance();
  const restoreMutation = useRestoreStrategyInstance();

  // Get templates from API (system templates)
  const templates = templatesData?.templates || [];
  const instances = instancesData?.instances?.filter(i => !i.is_system_template) || [];
  
  // Derive categories from templates
  const categories = useMemo(() => {
    const cats = new Set<string>();
    templates.forEach(t => {
      // Derive category from template_id
      const id = t.template_id;
      if (id.includes('reversion') || id.includes('fade') || id.includes('poc') || id.includes('vwap')) cats.add('mean_reversion');
      else if (id.includes('breakout') || id.includes('expansion')) cats.add('breakout');
      else if (id.includes('trend') || id.includes('momentum') || id.includes('pullback')) cats.add('trend_following');
      else if (id.includes('scalp') || id.includes('grind') || id.includes('compression')) cats.add('scalping');
      else cats.add('other');
    });
    return [...cats];
  }, [templates]);
  
  // Helper to get category for a template
  const getTemplateCategory = (templateId: string) => {
    if (templateId.includes('reversion') || templateId.includes('fade') || templateId.includes('poc') || templateId.includes('vwap')) return 'mean_reversion';
    if (templateId.includes('breakout') || templateId.includes('expansion')) return 'breakout';
    if (templateId.includes('trend') || templateId.includes('momentum') || templateId.includes('pullback')) return 'trend_following';
    if (templateId.includes('scalp') || templateId.includes('grind') || templateId.includes('compression')) return 'scalping';
    return 'other';
  };

  // Filter library templates from API
  const filteredLibrary = useMemo(() => {
    return templates.filter((t) => {
      const matchesSearch = !searchQuery || 
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (t.description || "").toLowerCase().includes(searchQuery.toLowerCase());
      const category = getTemplateCategory(t.template_id);
      const matchesCategory = categoryFilter === "all" || category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [templates, searchQuery, categoryFilter]);

  // Filter and sort instances
  const filteredInstances = useMemo(() => {
    let result = [...instances];

    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.template_id.toLowerCase().includes(q) ||
          (s.description || "").toLowerCase().includes(q)
      );
    }

    // Sort
    result.sort((a, b) => {
      switch (sortBy) {
        case "name":
          return a.name.localeCompare(b.name);
        case "usage":
          return (b.usage_count || 0) - (a.usage_count || 0);
        default:
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      }
    });

    return result;
  }, [instances, searchQuery, sortBy]);

  const handleOpenInstance = (instance: StrategyInstance) => {
    setSelectedInstance(instance);
    setInstanceDrawerOpen(true);
  };

  const handleCreateFromTemplate = (template: StrategyInstance) => {
    setPreselectedTemplate(template);
    setCreateDialogOpen(true);
  };

  const handleClone = (instance: StrategyInstance) => {
    cloneMutation.mutate(
      { id: instance.id },
      {
        onSuccess: () => {
          toast.success("Strategy instance cloned");
          setInstanceDrawerOpen(false);
        },
        onError: (err: any) => {
          toast.error(err?.response?.data?.message || "Failed to clone instance");
        },
      }
    );
  };

  const handleArchive = (instance: StrategyInstance) => {
    archiveMutation.mutate(instance.id, {
      onSuccess: () => {
        toast.success("Strategy instance archived");
        setInstanceDrawerOpen(false);
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.message || "Failed to archive instance");
      },
    });
  };

  const handleRestore = (instance: StrategyInstance) => {
    restoreMutation.mutate(instance.id, {
      onSuccess: () => {
        toast.success("Strategy instance restored");
        setInstanceDrawerOpen(false);
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.message || "Failed to restore instance");
      },
    });
  };

  return (
    <TooltipProvider>
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-primary uppercase tracking-wider mb-1">STRATEGIES</p>
            <h1 className="text-2xl font-bold tracking-tight">Strategy Management</h1>
            <p className="text-sm text-muted-foreground">
              Browse the strategy library and manage your customized instances
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => {
                setPreselectedTemplate(null);
                setCreateDialogOpen(true);
              }}
            >
              <Plus className="h-4 w-4 mr-2" />
              Create Instance
            </Button>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          <TabsList>
            <TabsTrigger value="library" className="gap-2">
              <BookOpen className="h-4 w-4" />
              Strategy Library
              <Badge variant="outline" className="ml-1 text-[10px]">{templates.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="instances" className="gap-2">
              <Layers className="h-4 w-4" />
              My Instances
              <Badge variant="outline" className="ml-1 text-[10px]">{instances.length}</Badge>
            </TabsTrigger>
          </TabsList>

          {/* Strategy Library Tab */}
          <TabsContent value="library" className="mt-6 space-y-4">
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 p-4 rounded-lg border border-border bg-muted/30">
              <div className="relative flex-1 min-w-[200px] max-w-xs">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search templates..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>

              <Select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                options={[
                  { value: "all", label: "All Categories" },
                  ...categories.map((c) => ({ value: c, label: c.replace(/_/g, " ") })),
                ]}
                className="w-[180px]"
              />

              <div className="ml-auto">
                <span className="text-sm text-muted-foreground">{filteredLibrary.length} templates</span>
              </div>
            </div>

            {/* Template Grid */}
            {loadingTemplates ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {filteredLibrary.map((template) => {
                  const category = getTemplateCategory(template.template_id);
                  return (
                    <Card key={template.id} className="border-border hover:border-primary/30 transition-colors">
                      <CardContent className="p-5">
                        <div className="flex items-start justify-between mb-3">
                          <Badge className={cn("text-xs", getCategoryColor(category))}>
                            {category.replace(/_/g, " ")}
                          </Badge>
                        </div>

                        <h3 className="font-semibold mb-1">{template.name}</h3>
                        <p className="text-sm text-muted-foreground mb-4 line-clamp-2">{template.description || "No description"}</p>

                        <div className="space-y-2 mb-4">
                          <p className="text-xs text-muted-foreground uppercase tracking-wider">Default Parameters</p>
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(template.params || {}).slice(0, 3).map(([key, value]) => (
                              <Badge key={key} variant="outline" className="text-[10px] font-mono">
                                {key}: {String(value)}
                              </Badge>
                            ))}
                            {Object.keys(template.params || {}).length > 3 && (
                              <Badge variant="outline" className="text-[10px]">
                                +{Object.keys(template.params || {}).length - 3} more
                              </Badge>
                            )}
                          </div>
                        </div>

                        <Button
                          variant="outline"
                          className="w-full"
                          onClick={() => handleCreateFromTemplate(template)}
                        >
                          <Sparkles className="h-4 w-4 mr-2" />
                          Create Instance
                        </Button>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}

            {filteredLibrary.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <BookOpen className="h-12 w-12 mb-4 opacity-30" />
                <p className="text-lg font-medium">No templates found</p>
                <p className="text-sm">Try adjusting your search or filters</p>
              </div>
            )}
          </TabsContent>

          {/* My Instances Tab */}
          <TabsContent value="instances" className="mt-6 space-y-4">
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3 p-4 rounded-lg border border-border bg-muted/30">
              <div className="relative flex-1 min-w-[200px] max-w-xs">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search instances..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>

              <Select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                options={[
                  { value: "all", label: "All Statuses" },
                  { value: "active", label: "Active" },
                  { value: "deprecated", label: "Deprecated" },
                  { value: "archived", label: "Archived" },
                ]}
                className="w-[140px]"
              />

              <div className="ml-auto flex items-center gap-2">
                <span className="text-sm text-muted-foreground">{filteredInstances.length} instances</span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="sm">
                      <ArrowUpDown className="h-4 w-4 mr-2" />
                      Sort
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem onClick={() => setSortBy("updated")}>
                      <Clock className="h-4 w-4 mr-2" />
                      Recently Updated
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => setSortBy("name")}>
                      <Tag className="h-4 w-4 mr-2" />
                      Name
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => setSortBy("usage")}>
                      <TrendingUp className="h-4 w-4 mr-2" />
                      Most Used
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>

            {/* Instances Table */}
            <Card className="border-border">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Instance</th>
                      <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Template</th>
                      <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Status</th>
                      <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Usage</th>
                      <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Version</th>
                      <th className="text-left p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Updated</th>
                      <th className="text-right p-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loadingInstances ? (
                      <tr>
                        <td colSpan={7} className="p-8 text-center">
                          <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                        </td>
                      </tr>
                    ) : (
                      filteredInstances.map((instance) => {
                        const category = deriveCategory(instance.template_id);
                        return (
                          <tr
                            key={instance.id}
                            className="border-b border-border/50 hover:bg-muted/20 cursor-pointer transition-colors"
                            onClick={() => handleOpenInstance(instance)}
                          >
                            <td className="p-3">
                              <div>
                                <p className="font-medium text-sm">{instance.name}</p>
                                <p className="text-xs text-muted-foreground truncate max-w-[200px]">
                                  {instance.description || "No description"}
                                </p>
                              </div>
                            </td>
                            <td className="p-3">
                              <Badge className={cn("text-[10px]", getCategoryColor(category))}>
                                {instance.template_id.replace(/_/g, " ")}
                              </Badge>
                            </td>
                            <td className="p-3">
                              <Badge className={cn("text-[10px]", getStatusColor(instance.status))}>
                                {instance.status}
                              </Badge>
                            </td>
                            <td className="p-3">
                              <span className="text-sm">
                                {instance.usage_count || 0} profile{(instance.usage_count || 0) !== 1 ? "s" : ""}
                              </span>
                            </td>
                            <td className="p-3">
                              <span className="text-sm font-mono">v{instance.version}</span>
                            </td>
                            <td className="p-3">
                              <span className="text-xs text-muted-foreground">
                                {new Date(instance.updated_at).toLocaleDateString()}
                              </span>
                            </td>
                            <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                                    <MoreHorizontal className="h-4 w-4" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem onClick={() => handleOpenInstance(instance)}>
                                    <Settings className="h-4 w-4 mr-2" />
                                    View Details
                                  </DropdownMenuItem>
                                  <DropdownMenuItem onClick={() => handleClone(instance)}>
                                    <Copy className="h-4 w-4 mr-2" />
                                    Clone
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  {instance.status === "archived" ? (
                                    <DropdownMenuItem onClick={() => handleRestore(instance)}>
                                      <RotateCcw className="h-4 w-4 mr-2" />
                                      Restore
                                    </DropdownMenuItem>
                                  ) : (
                                    <DropdownMenuItem
                                      className="text-amber-500"
                                      onClick={() => handleArchive(instance)}
                                    >
                                      <Archive className="h-4 w-4 mr-2" />
                                      Archive
                                    </DropdownMenuItem>
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {!loadingInstances && filteredInstances.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <Zap className="h-12 w-12 mb-4 opacity-30" />
                  <p className="text-lg font-medium">No strategy instances</p>
                  <p className="text-sm">Create your first instance from the Strategy Library</p>
                  <Button
                    variant="outline"
                    className="mt-4"
                    onClick={() => setActiveTab("library")}
                  >
                    <BookOpen className="h-4 w-4 mr-2" />
                    Browse Library
                  </Button>
                </div>
              )}
            </Card>
          </TabsContent>
        </Tabs>

        {/* Instance Drawer */}
        <StrategyInstanceDrawer
          instance={selectedInstance}
          isOpen={instanceDrawerOpen}
          onClose={() => setInstanceDrawerOpen(false)}
          onClone={handleClone}
          onArchive={handleArchive}
          onRestore={handleRestore}
        />

        {/* Create Instance Dialog */}
        <CreateInstanceDialog
          isOpen={createDialogOpen}
          onClose={() => {
            setCreateDialogOpen(false);
            setPreselectedTemplate(null);
          }}
          preselectedTemplate={preselectedTemplate}
        />
      </div>
    </TooltipProvider>
  );
}
