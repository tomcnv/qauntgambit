import { useState, useEffect, useMemo } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import {
  Save,
  X,
  Plus,
  Loader2,
  Shield,
  Activity,
  Target,
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  ArrowRight,
  Layers,
  Settings,
  Zap,
  History,
  GitBranch,
  Trash2,
  GripVertical,
  AlertCircle,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Select } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { Slider } from "../../components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { cn } from "../../lib/utils";
import {
  useUserProfile,
  useUserProfiles,
  useCreateUserProfile,
  useUpdateUserProfile,
  usePromoteUserProfile,
  useStrategyInstances,
} from "../../lib/api/hooks";
import {
  UserProfile,
  StrategyComposition,
  ProfileRiskConfig,
  ProfileConditions,
  ProfileLifecycle,
  ProfileExecution,
  StrategyInstance,
} from "../../lib/api/client";

// ============================================================================
// TYPES
// ============================================================================

interface ProfileFormData {
  name: string;
  description: string;
  baseProfileId: string | null;
  environment: "dev" | "paper" | "live";
  strategyComposition: StrategyComposition[];
  riskConfig: ProfileRiskConfig;
  conditions: ProfileConditions;
  lifecycle: ProfileLifecycle;
  execution: ProfileExecution;
  tags: string[];
}

const defaultFormData: ProfileFormData = {
  name: "",
  description: "",
  baseProfileId: null,
  environment: "dev",
  strategyComposition: [],
  riskConfig: {
    risk_per_trade_pct: 1.0,
    max_leverage: 1.0,
    max_positions: 4,
    stop_loss_pct: 0.5,
    take_profit_pct: 1.5,
    max_drawdown_pct: 5.0,
    max_daily_loss_pct: 3.0,
  },
  conditions: {
    required_session: "any",
    required_volatility: "any",
    required_trend: "any",
    max_spread_bps: 20,
    min_depth_usd: 5000,
  },
  lifecycle: {
    cooldown_seconds: 60,
    disable_after_consecutive_losses: 5,
    protection_mode_threshold_pct: 50,
    warmup_seconds: 300,
    max_trades_per_hour: 20,
  },
  execution: {
    order_type_preference: "bracket",
    maker_taker_bias: 0.5,
    max_slippage_bps: 5,
    time_in_force: "GTC",
    reduce_only_exits: true,
  },
  tags: [],
};

// ============================================================================
// HELPER COMPONENTS
// ============================================================================

function EnvironmentBadge({ environment }: { environment: string }) {
  const colorMap: Record<string, string> = {
    dev: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    paper: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    live: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  };
  return (
    <Badge className={cn("text-[10px] uppercase", colorMap[environment] || "")}>
      {environment}
    </Badge>
  );
}

function SectionCard({
  title,
  description,
  icon: Icon,
  children,
  defaultOpen = true,
}: {
  title: string;
  description?: string;
  icon?: React.ElementType;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <Card className="border-border">
      <CardHeader
        className="cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {Icon && <Icon className="h-5 w-5 text-muted-foreground" />}
            <div>
              <CardTitle className="text-base">{title}</CardTitle>
              {description && <CardDescription className="text-xs">{description}</CardDescription>}
            </div>
          </div>
          {isOpen ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
      </CardHeader>
      {isOpen && <CardContent className="pt-0">{children}</CardContent>}
    </Card>
  );
}

function StrategyCompositionEditor({
  composition,
  onChange,
  instances,
  loadingInstances,
}: {
  composition: StrategyComposition[];
  onChange: (composition: StrategyComposition[]) => void;
  instances: StrategyInstance[];
  loadingInstances: boolean;
}) {
  const [showAddDialog, setShowAddDialog] = useState(false);

  const handleAdd = (instanceId: string) => {
    const newItem: StrategyComposition = {
      instance_id: instanceId,
      weight: 1.0,
      priority: composition.length + 1,
      enabled: true,
    };
    onChange([...composition, newItem]);
    setShowAddDialog(false);
  };

  const handleRemove = (instanceId: string) => {
    onChange(composition.filter((c) => c.instance_id !== instanceId));
  };

  const handleUpdate = (instanceId: string, updates: Partial<StrategyComposition>) => {
    onChange(
      composition.map((c) =>
        c.instance_id === instanceId ? { ...c, ...updates } : c
      )
    );
  };

  const availableInstances = instances.filter(
    (i) => !composition.some((c) => c.instance_id === i.id) && i.status === "active"
  );

  return (
    <div className="space-y-4">
      {composition.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground border border-dashed border-border rounded-lg">
          <Layers className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No strategies added yet</p>
          <p className="text-xs">Add strategy instances to compose this profile</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => setShowAddDialog(true)}
          >
            <Plus className="h-4 w-4 mr-2" />
            Add Strategy
          </Button>
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {composition.map((item, index) => {
              const instance = instances.find((i) => i.id === item.instance_id);
              return (
                <div
                  key={item.instance_id}
                  className={cn(
                    "p-4 rounded-lg border transition-colors",
                    item.enabled ? "border-border bg-card" : "border-border/50 bg-muted/30 opacity-60"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <GripVertical className="h-4 w-4" />
                      <span className="text-xs font-mono w-4">{index + 1}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-medium text-sm truncate">
                          {instance?.name || item.instance_id}
                        </span>
                        {!item.enabled && (
                          <Badge variant="outline" className="text-[10px]">Disabled</Badge>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-4 mt-3">
                        <div className="space-y-1">
                          <Label className="text-xs text-muted-foreground">Weight</Label>
                          <Input
                            type="number"
                            min={0.1}
                            max={10}
                            step={0.1}
                            value={item.weight}
                            onChange={(e) =>
                              handleUpdate(item.instance_id, { weight: parseFloat(e.target.value) || 1 })
                            }
                            className="h-8 text-sm"
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs text-muted-foreground">Priority</Label>
                          <Input
                            type="number"
                            min={1}
                            max={10}
                            value={item.priority}
                            onChange={(e) =>
                              handleUpdate(item.instance_id, { priority: parseInt(e.target.value) || 1 })
                            }
                            className="h-8 text-sm"
                          />
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={item.enabled}
                        onChange={(e) => handleUpdate(item.instance_id, { enabled: e.target.checked })}
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                        onClick={() => handleRemove(item.instance_id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <Button variant="outline" size="sm" onClick={() => setShowAddDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add Strategy
          </Button>
        </>
      )}

      {/* Add Strategy Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Add Strategy Instance</DialogTitle>
            <DialogDescription>
              Select a strategy instance to add to this profile
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {loadingInstances ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : availableInstances.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p className="text-sm">No available strategy instances</p>
                <p className="text-xs">Create instances in the Strategies page</p>
              </div>
            ) : (
              availableInstances.map((instance) => (
                <button
                  key={instance.id}
                  onClick={() => handleAdd(instance.id)}
                  className="w-full p-3 rounded-lg border border-border hover:border-primary/50 hover:bg-muted/30 transition-colors text-left"
                >
                  <p className="font-medium text-sm">{instance.name}</p>
                  <p className="text-xs text-muted-foreground">{instance.template_id}</p>
                </button>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function VersionHistorySheet({
  isOpen,
  onClose,
  versions,
  currentVersion,
}: {
  isOpen: boolean;
  onClose: () => void;
  versions: any[];
  currentVersion: number;
}) {
  return (
    <Sheet open={isOpen} onOpenChange={onClose}>
      <SheetContent className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Version History</SheetTitle>
          <SheetDescription>
            Track all changes made to this profile
          </SheetDescription>
        </SheetHeader>
        <div className="mt-6 space-y-3">
          {versions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <History className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No version history yet</p>
            </div>
          ) : (
            versions.map((v) => (
              <div
                key={v.id}
                className={cn(
                  "p-4 rounded-lg border",
                  v.version === currentVersion
                    ? "border-primary/50 bg-primary/5"
                    : "border-border"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">v{v.version}</Badge>
                    {v.version === currentVersion && (
                      <Badge className="text-[10px] bg-primary/20 text-primary">Current</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {new Date(v.created_at).toLocaleDateString()}
                  </span>
                </div>
                {v.change_reason && (
                  <p className="text-xs text-muted-foreground">{v.change_reason}</p>
                )}
              </div>
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ============================================================================
// MAIN PAGE
// ============================================================================

export default function ProfileEditorPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const profileId = searchParams.get("id");

  const [formData, setFormData] = useState<ProfileFormData>(defaultFormData);
  const [isDirty, setIsDirty] = useState(false);
  const [activeTab, setActiveTab] = useState<"composition" | "risk" | "gates" | "lifecycle" | "execution">("composition");
  const [showVersionHistory, setShowVersionHistory] = useState(false);
  const [changeReason, setChangeReason] = useState("");
  const [showPromoteDialog, setShowPromoteDialog] = useState(false);
  const [promotionNotes, setPromotionNotes] = useState("");

  // API hooks
  const { data: profileData, isLoading: loadingProfile } = useUserProfile(profileId || "");
  const { data: instancesData, isLoading: loadingInstances } = useStrategyInstances({ status: "active" });
  const createMutation = useCreateUserProfile();
  const updateMutation = useUpdateUserProfile();
  const promoteMutation = usePromoteUserProfile();

  const instances = instancesData?.instances || [];
  const profile = profileData?.profile;
  const isEditing = !!profileId && !!profile;

  // Load profile data
  useEffect(() => {
    if (profile) {
      setFormData({
        name: profile.name,
        description: profile.description || "",
        baseProfileId: profile.base_profile_id,
        environment: profile.environment,
        strategyComposition: profile.strategy_composition || [],
        riskConfig: profile.risk_config || defaultFormData.riskConfig,
        conditions: profile.conditions || defaultFormData.conditions,
        lifecycle: profile.lifecycle || defaultFormData.lifecycle,
        execution: profile.execution || defaultFormData.execution,
        tags: profile.tags || [],
      });
    }
  }, [profile]);

  const updateField = <K extends keyof ProfileFormData>(field: K, value: ProfileFormData[K]) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setIsDirty(true);
  };

  const updateRiskConfig = (key: keyof ProfileRiskConfig, value: any) => {
    setFormData((prev) => ({
      ...prev,
      riskConfig: { ...prev.riskConfig, [key]: value },
    }));
    setIsDirty(true);
  };

  const updateConditions = (key: keyof ProfileConditions, value: any) => {
    setFormData((prev) => ({
      ...prev,
      conditions: { ...prev.conditions, [key]: value },
    }));
    setIsDirty(true);
  };

  const updateLifecycle = (key: keyof ProfileLifecycle, value: any) => {
    setFormData((prev) => ({
      ...prev,
      lifecycle: { ...prev.lifecycle, [key]: value },
    }));
    setIsDirty(true);
  };

  const updateExecution = (key: keyof ProfileExecution, value: any) => {
    setFormData((prev) => ({
      ...prev,
      execution: { ...prev.execution, [key]: value },
    }));
    setIsDirty(true);
  };

  const handleSave = () => {
    if (!formData.name.trim()) {
      toast.error("Profile name is required");
      return;
    }

    if (isEditing && profile.environment === "live" && !changeReason.trim()) {
      toast.error("Change reason is required for Live profiles");
      return;
    }

    const payload = {
      name: formData.name,
      description: formData.description || undefined,
      strategyComposition: formData.strategyComposition,
      riskConfig: formData.riskConfig,
      conditions: formData.conditions,
      lifecycle: formData.lifecycle,
      execution: formData.execution,
      tags: formData.tags,
      changeReason: changeReason || undefined,
    };

    if (isEditing) {
      updateMutation.mutate(
        { id: profileId!, data: payload },
        {
          onSuccess: () => {
            toast.success("Profile updated");
            setIsDirty(false);
            setChangeReason("");
          },
          onError: (err: any) => {
            toast.error(err?.response?.data?.message || "Failed to update profile");
          },
        }
      );
    } else {
      createMutation.mutate(
        { ...payload, environment: formData.environment },
        {
          onSuccess: (data) => {
            toast.success("Profile created");
            navigate(`/dashboard/profile-editor?id=${data.profile.id}`);
          },
          onError: (err: any) => {
            toast.error(err?.response?.data?.message || "Failed to create profile");
          },
        }
      );
    }
  };

  const handlePromote = () => {
    if (!profileId) return;

    promoteMutation.mutate(
      { id: profileId, notes: promotionNotes || undefined },
      {
        onSuccess: (data) => {
          toast.success(data.message);
          setShowPromoteDialog(false);
          setPromotionNotes("");
          navigate(`/dashboard/profile-editor?id=${data.profile.id}`);
        },
        onError: (err: any) => {
          toast.error(err?.response?.data?.message || "Failed to promote profile");
        },
      }
    );
  };

  const getNextEnvironment = () => {
    if (!profile) return null;
    if (profile.environment === "dev") return "paper";
    if (profile.environment === "paper") return "live";
    return null;
  };

  const nextEnv = getNextEnvironment();
  const isSaving = createMutation.isPending || updateMutation.isPending;

  if (loadingProfile && profileId) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full pb-24">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-primary uppercase tracking-wider mb-1">PROFILE EDITOR</p>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">
                {isEditing ? formData.name || "Untitled Profile" : "New Profile"}
              </h1>
              {isEditing && profile && (
                <>
                  <EnvironmentBadge environment={profile.environment} />
                  <Badge variant="outline" className="text-xs">v{profile.version}</Badge>
                </>
              )}
            </div>
            {isEditing && profile?.description && (
              <p className="text-sm text-muted-foreground mt-1">{profile.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => navigate("/dashboard/profiles")}>
              <X className="h-4 w-4 mr-2" />
              Cancel
            </Button>
            {isEditing && (
              <Button variant="outline" onClick={() => setShowVersionHistory(true)}>
                <History className="h-4 w-4 mr-2" />
                History
              </Button>
            )}
            {isEditing && nextEnv && (
              <Button variant="outline" onClick={() => setShowPromoteDialog(true)}>
                <GitBranch className="h-4 w-4 mr-2" />
                Promote to {nextEnv.charAt(0).toUpperCase() + nextEnv.slice(1)}
              </Button>
            )}
            <Button onClick={handleSave} disabled={isSaving || (!isDirty && isEditing)}>
              {isSaving ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-2" />
              )}
              {isEditing ? "Save Changes" : "Create Profile"}
            </Button>
          </div>
        </div>

        {/* Dirty indicator */}
        {isDirty && (
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-500 text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            You have unsaved changes
          </div>
        )}

        {/* Basic Info (always visible) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Basic Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Profile Name *</Label>
                <Input
                  value={formData.name}
                  onChange={(e) => updateField("name", e.target.value)}
                  placeholder="e.g., Momentum Scalp - US Session"
                />
              </div>
              {!isEditing && (
                <div className="space-y-2">
                  <Label>Environment</Label>
                  <Select
                    value={formData.environment}
                    onChange={(e) => updateField("environment", e.target.value as any)}
                    options={[
                      { value: "dev", label: "Development" },
                      { value: "paper", label: "Paper Trading" },
                      { value: "live", label: "Live Trading" },
                    ]}
                  />
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <textarea
                value={formData.description}
                onChange={(e) => updateField("description", e.target.value)}
                placeholder="Describe when this profile should be used..."
                className="w-full min-h-[80px] px-3 py-2 text-sm rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/60"
              />
            </div>
            {isEditing && profile?.environment === "live" && (
              <div className="space-y-2">
                <Label>Change Reason (required for Live) *</Label>
                <Input
                  value={changeReason}
                  onChange={(e) => setChangeReason(e.target.value)}
                  placeholder="Why are you making this change?"
                />
              </div>
            )}
          </CardContent>
        </Card>

        {/* Tabs for Configuration Sections */}
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="composition" className="gap-2">
              <Layers className="h-4 w-4" />
              <span className="hidden sm:inline">Strategies</span>
            </TabsTrigger>
            <TabsTrigger value="risk" className="gap-2">
              <Shield className="h-4 w-4" />
              <span className="hidden sm:inline">Risk</span>
            </TabsTrigger>
            <TabsTrigger value="gates" className="gap-2">
              <Target className="h-4 w-4" />
              <span className="hidden sm:inline">Gates</span>
            </TabsTrigger>
            <TabsTrigger value="lifecycle" className="gap-2">
              <Activity className="h-4 w-4" />
              <span className="hidden sm:inline">Lifecycle</span>
            </TabsTrigger>
            <TabsTrigger value="execution" className="gap-2">
              <Zap className="h-4 w-4" />
              <span className="hidden sm:inline">Execution</span>
            </TabsTrigger>
          </TabsList>

          {/* Strategy Composition */}
          <TabsContent value="composition" className="mt-6">
            <SectionCard
              title="Strategy Composition"
              description="Add and configure strategy instances for this profile"
              icon={Layers}
            >
              <StrategyCompositionEditor
                composition={formData.strategyComposition}
                onChange={(c) => updateField("strategyComposition", c)}
                instances={instances}
                loadingInstances={loadingInstances}
              />
            </SectionCard>
          </TabsContent>

          {/* Risk Controls */}
          <TabsContent value="risk" className="mt-6 space-y-4">
            <SectionCard
              title="Position Sizing"
              description="Control risk per trade and leverage"
              icon={Shield}
            >
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Risk Per Trade (%)</Label>
                  <Input
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    value={formData.riskConfig.risk_per_trade_pct || 1}
                    onChange={(e) => updateRiskConfig("risk_per_trade_pct", parseFloat(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Leverage</Label>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    step={0.5}
                    value={formData.riskConfig.max_leverage || 1}
                    onChange={(e) => updateRiskConfig("max_leverage", parseFloat(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Open Positions</Label>
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={formData.riskConfig.max_positions || 4}
                    onChange={(e) => updateRiskConfig("max_positions", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Daily Loss (%)</Label>
                  <Input
                    type="number"
                    min={0.5}
                    max={20}
                    step={0.5}
                    value={formData.riskConfig.max_daily_loss_pct || 3}
                    onChange={(e) => updateRiskConfig("max_daily_loss_pct", parseFloat(e.target.value))}
                  />
                </div>
              </div>
            </SectionCard>

            <SectionCard
              title="Stop Loss / Take Profit"
              description="Configure exit levels"
              icon={Target}
            >
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Stop Loss (%)</Label>
                  <Input
                    type="number"
                    min={0.1}
                    max={10}
                    step={0.1}
                    value={formData.riskConfig.stop_loss_pct || 0.5}
                    onChange={(e) => updateRiskConfig("stop_loss_pct", parseFloat(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Take Profit (%)</Label>
                  <Input
                    type="number"
                    min={0.1}
                    max={20}
                    step={0.1}
                    value={formData.riskConfig.take_profit_pct || 1.5}
                    onChange={(e) => updateRiskConfig("take_profit_pct", parseFloat(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Drawdown (%)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={50}
                    step={0.5}
                    value={formData.riskConfig.max_drawdown_pct || 5}
                    onChange={(e) => updateRiskConfig("max_drawdown_pct", parseFloat(e.target.value))}
                  />
                </div>
              </div>
            </SectionCard>
          </TabsContent>

          {/* Market Condition Gates */}
          <TabsContent value="gates" className="mt-6">
            <SectionCard
              title="Market Condition Gates"
              description="Define when this profile should be active"
              icon={Target}
            >
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <div className="space-y-2">
                  <Label>Required Session</Label>
                  <Select
                    value={formData.conditions.required_session || "any"}
                    onChange={(e) => updateConditions("required_session", e.target.value)}
                    options={[
                      { value: "any", label: "Any Session" },
                      { value: "asia", label: "Asia" },
                      { value: "europe", label: "Europe" },
                      { value: "us", label: "US" },
                      { value: "overnight", label: "Overnight" },
                    ]}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Required Volatility</Label>
                  <Select
                    value={formData.conditions.required_volatility || "any"}
                    onChange={(e) => updateConditions("required_volatility", e.target.value)}
                    options={[
                      { value: "any", label: "Any" },
                      { value: "low", label: "Low" },
                      { value: "normal", label: "Normal" },
                      { value: "high", label: "High" },
                    ]}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Required Trend</Label>
                  <Select
                    value={formData.conditions.required_trend || "any"}
                    onChange={(e) => updateConditions("required_trend", e.target.value)}
                    options={[
                      { value: "any", label: "Any" },
                      { value: "up", label: "Uptrend" },
                      { value: "down", label: "Downtrend" },
                      { value: "flat", label: "Flat/Range" },
                    ]}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Spread (bps)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={formData.conditions.max_spread_bps || 20}
                    onChange={(e) => updateConditions("max_spread_bps", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Min Depth (USD)</Label>
                  <Input
                    type="number"
                    min={100}
                    max={1000000}
                    value={formData.conditions.min_depth_usd || 5000}
                    onChange={(e) => updateConditions("min_depth_usd", parseInt(e.target.value))}
                  />
                </div>
              </div>
            </SectionCard>
          </TabsContent>

          {/* Lifecycle Rules */}
          <TabsContent value="lifecycle" className="mt-6">
            <SectionCard
              title="Lifecycle Rules"
              description="Configure cooldowns and protection modes"
              icon={Activity}
            >
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Cooldown Between Trades (seconds)</Label>
                  <Input
                    type="number"
                    min={0}
                    max={3600}
                    value={formData.lifecycle.cooldown_seconds || 60}
                    onChange={(e) => updateLifecycle("cooldown_seconds", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Warmup Period (seconds)</Label>
                  <Input
                    type="number"
                    min={0}
                    max={3600}
                    value={formData.lifecycle.warmup_seconds || 300}
                    onChange={(e) => updateLifecycle("warmup_seconds", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Disable After Consecutive Losses</Label>
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={formData.lifecycle.disable_after_consecutive_losses || 5}
                    onChange={(e) => updateLifecycle("disable_after_consecutive_losses", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Trades Per Hour</Label>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={formData.lifecycle.max_trades_per_hour || 20}
                    onChange={(e) => updateLifecycle("max_trades_per_hour", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Protection Mode Threshold (%)</Label>
                  <Input
                    type="number"
                    min={10}
                    max={90}
                    value={formData.lifecycle.protection_mode_threshold_pct || 50}
                    onChange={(e) => updateLifecycle("protection_mode_threshold_pct", parseInt(e.target.value))}
                  />
                  <p className="text-xs text-muted-foreground">
                    Enable protection when profit reaches this % of max daily loss
                  </p>
                </div>
              </div>
            </SectionCard>
          </TabsContent>

          {/* Execution Preferences */}
          <TabsContent value="execution" className="mt-6">
            <SectionCard
              title="Execution Preferences"
              description="Configure order types and slippage limits"
              icon={Zap}
            >
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Order Type Preference</Label>
                  <Select
                    value={formData.execution.order_type_preference || "bracket"}
                    onChange={(e) => updateExecution("order_type_preference", e.target.value)}
                    options={[
                      { value: "market", label: "Market" },
                      { value: "limit", label: "Limit" },
                      { value: "bracket", label: "Bracket (with SL/TP)" },
                      { value: "oco", label: "OCO" },
                    ]}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Time in Force</Label>
                  <Select
                    value={formData.execution.time_in_force || "GTC"}
                    onChange={(e) => updateExecution("time_in_force", e.target.value)}
                    options={[
                      { value: "GTC", label: "Good Till Cancel" },
                      { value: "IOC", label: "Immediate or Cancel" },
                      { value: "FOK", label: "Fill or Kill" },
                    ]}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Slippage (bps)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={formData.execution.max_slippage_bps || 5}
                    onChange={(e) => updateExecution("max_slippage_bps", parseInt(e.target.value))}
                  />
                </div>
                <div className="space-y-4">
                  <Label>Maker/Taker Bias</Label>
                  <div className="px-2">
                    <Slider
                      value={[(formData.execution.maker_taker_bias || 0.5) * 100]}
                      onValueChange={(v) => updateExecution("maker_taker_bias", v[0] / 100)}
                      min={0}
                      max={100}
                      step={10}
                    />
                    <div className="flex justify-between text-xs text-muted-foreground mt-1">
                      <span>Full Maker</span>
                      <span>Full Taker</span>
                    </div>
                  </div>
                </div>
              </div>
              <Separator className="my-4" />
              <div className="flex items-center justify-between p-4 rounded-lg border border-border">
                <div>
                  <p className="text-sm font-medium">Reduce Only Exits</p>
                  <p className="text-xs text-muted-foreground">
                    Only use reduce-only orders when closing positions
                  </p>
                </div>
                <Switch
                  checked={formData.execution.reduce_only_exits ?? true}
                  onChange={(e) => updateExecution("reduce_only_exits", e.target.checked)}
                />
              </div>
            </SectionCard>
          </TabsContent>
        </Tabs>

        {/* Version History Sheet */}
        {isEditing && profile && (
          <VersionHistorySheet
            isOpen={showVersionHistory}
            onClose={() => setShowVersionHistory(false)}
            versions={profile.versions || []}
            currentVersion={profile.version}
          />
        )}

        {/* Promote Dialog */}
        <Dialog open={showPromoteDialog} onOpenChange={setShowPromoteDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Promote Profile</DialogTitle>
              <DialogDescription>
                Promote this profile from {profile?.environment} to {nextEnv}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              {profile?.environment === "paper" && (
                <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-500 text-sm">
                  <div className="flex items-center gap-2 font-medium mb-1">
                    <AlertTriangle className="h-4 w-4" />
                    Live Promotion Warning
                  </div>
                  <p className="text-xs">
                    You're about to promote to Live trading. Make sure you've tested thoroughly in Paper mode.
                    Paper trades: {profile.paper_trades_count || 0}
                  </p>
                </div>
              )}
              <div className="space-y-2">
                <Label>Promotion Notes</Label>
                <textarea
                  value={promotionNotes}
                  onChange={(e) => setPromotionNotes(e.target.value)}
                  placeholder="Why are you promoting this profile?"
                  className="w-full min-h-[80px] px-3 py-2 text-sm rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/60"
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowPromoteDialog(false)}>
                Cancel
              </Button>
              <Button onClick={handlePromote} disabled={promoteMutation.isPending}>
                {promoteMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Promote to {nextEnv?.charAt(0).toUpperCase()}{nextEnv?.slice(1)}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  );
}
