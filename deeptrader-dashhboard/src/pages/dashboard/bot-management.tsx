/**
 * Bot Management Page
 * 
 * A comprehensive bot management system with:
 * - Fleet Dashboard: Monitor and manage all bots at a glance
 * - Bot Builder: Create and edit bots with a guided wizard
 * - Bot Detail: Deep configuration and versioning
 * 
 * Design Philosophy:
 * - Fleet ops: "What's running? Is it healthy? How's it doing?"
 * - Configuration: "Set up a bot safely and quickly, without getting lost."
 */

import { useState } from "react";
import { cn } from "../../lib/utils";
import { DashBar } from "../../components/DashBar";
import {
  Plus,
  Loader2,
  Shield,
  AlertCircle,
  Zap,
  Settings,
  ChevronRight,
  TrendingDown,
  Layers,
  ArrowRight,
  Server,
  Database,
  BarChart3,
  PieChart,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { TooltipProvider } from "../../components/ui/tooltip";

import { useTenantRiskPolicy } from "../../lib/api/hooks";
import type { BotInstance } from "../../lib/api/types";

// Import modular components
import { BotEditSheet, BotBuilder, FleetDashboard } from "../../components/bot-management";
import { getEnvironmentBadge } from "../../components/bot-management/types";

// ═══════════════════════════════════════════════════════════════
// NOTE: Constants and helper functions are imported from:
// ../../components/bot-management/types
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════

export default function BotManagementPage() {
  const [activeTab, setActiveTab] = useState<"fleet" | "builder" | "policy">("fleet");
  const [cloningBot, setCloningBot] = useState<BotInstance | null>(null);
  const [editSheetBot, setEditSheetBot] = useState<BotInstance | null>(null);

  const handleStartBuilder = (mode: "blank" | "template" | "clone", sourceBot?: BotInstance) => {
    if (mode === "clone" && sourceBot) {
      setCloningBot(sourceBot);
    } else {
      setCloningBot(null);
    }
    setActiveTab("builder");
  };

  const handleEditBot = (bot: BotInstance) => {
    // Open the edit sheet instead of going to builder
    setEditSheetBot(bot);
  };

  return (
    <>
      <DashBar />
      <TooltipProvider>
        <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Bot Management</h1>
              <p className="text-sm text-muted-foreground">
                Fleet operations, bot configuration, and deployment
              </p>
            </div>
          <div className="flex items-center gap-3">
            <Button
              variant={activeTab === "builder" ? "default" : "outline"}
              size="sm"
              onClick={() => handleStartBuilder("blank")}
            >
              <Plus className="h-4 w-4 mr-2" />
              Create Bot
            </Button>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          <TabsList className="w-full max-w-md">
            <TabsTrigger value="fleet" className="flex-1">
              <Layers className="h-4 w-4 mr-2" />
              Fleet
            </TabsTrigger>
            <TabsTrigger value="builder" className="flex-1">
              <Settings className="h-4 w-4 mr-2" />
              Bot Builder
            </TabsTrigger>
            <TabsTrigger value="policy" className="flex-1">
              <Shield className="h-4 w-4 mr-2" />
              Policy
            </TabsTrigger>
          </TabsList>

          <TabsContent value="fleet" className="mt-6">
            <FleetDashboard
              onCreateBot={() => handleStartBuilder("blank")}
              onEditBot={handleEditBot}
              onCloneBot={(bot) => handleStartBuilder("clone", bot)}
            />
          </TabsContent>

          <TabsContent value="builder" className="mt-6">
            <BotBuilder
              editingBot={cloningBot}
              onCancel={() => {
                setCloningBot(null);
                setActiveTab("fleet");
              }}
              onComplete={() => {
                setCloningBot(null);
                setActiveTab("fleet");
              }}
            />
          </TabsContent>

          <TabsContent value="policy" className="mt-6">
            <AccountPolicyPanel />
          </TabsContent>
        </Tabs>

        {/* Bot Edit Sheet */}
        <BotEditSheet
          bot={editSheetBot}
          onClose={() => setEditSheetBot(null)}
        />
        </div>
      </TooltipProvider>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// START OPTION CARD
// ═══════════════════════════════════════════════════════════════

interface StartOptionCardProps {
  selected: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  description: string;
  badge?: string;
  disabled?: boolean;
  disabledReason?: string;
}

function StartOptionCard({ selected, onClick, icon, title, description, badge, disabled, disabledReason }: StartOptionCardProps) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={cn(
        "relative rounded-xl border p-6 text-left transition-all",
        disabled
          ? "border-border/50 bg-muted/20 opacity-60 cursor-not-allowed"
          : selected
          ? "border-primary bg-primary/10 shadow-lg"
          : "border-border hover:border-primary/50 hover:bg-muted/30"
      )}
    >
      {badge && (
        <Badge className={cn(
          "absolute top-3 right-3 text-[10px]",
          disabled ? "bg-muted text-muted-foreground" : "bg-primary"
        )}>
          {badge}
        </Badge>
      )}
      <div className={cn(
        "mb-4",
        disabled ? "text-muted-foreground/50" : selected ? "text-primary" : "text-muted-foreground"
      )}>
        {icon}
      </div>
      <h3 className={cn("font-semibold mb-1", disabled && "text-muted-foreground")}>{title}</h3>
      <p className="text-sm text-muted-foreground">{description}</p>
      {disabled && disabledReason && (
        <p className="text-xs text-amber-500 mt-2 flex items-center gap-1">
          <AlertCircle className="h-3 w-3" />
          {disabledReason}
        </p>
      )}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════
// ACCOUNT POLICY PANEL
// ═══════════════════════════════════════════════════════════════

function AccountPolicyPanel() {
  const { data: policyData, isLoading } = useTenantRiskPolicy();
  const policy = policyData?.policy;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!policy) {
    return (
      <Card className="border-border/50">
        <CardContent className="py-12 text-center">
          <Shield className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
          <h3 className="font-semibold mb-2">No Policy Configured</h3>
          <p className="text-sm text-muted-foreground">Contact support to set up your risk policy</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Policy Hierarchy Explanation */}
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="py-4">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/20 p-2 mt-0.5">
              <Shield className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-sm mb-1">Policy Hierarchy</h3>
              <p className="text-xs text-muted-foreground mb-3">
                Policies cascade down — each level can be <span className="text-primary font-medium">stricter</span>, but never looser than its parent.
              </p>
              <div className="flex items-center gap-2 text-xs">
                <Badge variant="outline" className="bg-primary/10">Account Policy</Badge>
                <ChevronRight className="h-3 w-3 text-muted-foreground" />
                <Badge variant="outline">Exchange Policy</Badge>
                <ChevronRight className="h-3 w-3 text-muted-foreground" />
                <Badge variant="outline">Bot Budget</Badge>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Account Policy (Current Level) */}
      <Card className="border-border/50">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
                Account Policy
                <Badge className="ml-2 text-[10px]">This Level</Badge>
          </CardTitle>
          <CardDescription>
                Global limits that apply to ALL exchanges and ALL bots in your account
          </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <PolicyItem
              label="Max Daily Loss"
              value={`${policy.max_daily_loss_pct}%`}
              icon={<TrendingDown className="h-4 w-4" />}
            />
            <PolicyItem
              label="Max Leverage"
              value={`${policy.max_leverage}x`}
              icon={<BarChart3 className="h-4 w-4" />}
            />
            <PolicyItem
              label="Max Positions"
              value={policy.max_concurrent_positions}
              icon={<Layers className="h-4 w-4" />}
            />
            <PolicyItem
              label="Max Exposure"
              value={`${policy.max_total_exposure_pct}%`}
              icon={<PieChart className="h-4 w-4" />}
            />
            <PolicyItem
              label="Max Symbols"
              value={policy.max_symbols}
              icon={<Database className="h-4 w-4" />}
            />
            <PolicyItem
              label="Live Trading"
              value={policy.live_trading_enabled ? "Enabled" : "Disabled"}
              icon={<Zap className="h-4 w-4" />}
              highlight={policy.live_trading_enabled}
            />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="text-base">Allowed Environments</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            {policy.allowed_environments.map(env => (
              <Badge key={env} className={getEnvironmentBadge(env)}>{env}</Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="text-base">Circuit Breaker</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <Badge variant={policy.circuit_breaker_enabled ? "default" : "outline"}>
              {policy.circuit_breaker_enabled ? "Enabled" : "Disabled"}
            </Badge>
            {policy.circuit_breaker_enabled && (
              <span className="text-sm text-muted-foreground">
                Triggers at {policy.circuit_breaker_loss_pct}% loss, {policy.circuit_breaker_cooldown_minutes}min cooldown
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Link to Exchange Policies */}
      <Card className="border-dashed border-border/50 bg-muted/30">
        <CardContent className="py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Server className="h-8 w-8 text-muted-foreground" />
              <div>
                <h3 className="font-medium">Exchange-Level Policies</h3>
                <p className="text-sm text-muted-foreground">
                  Configure per-exchange limits (kill switch, max margin, daily loss) in Exchange Accounts
                </p>
              </div>
            </div>
            <Button asChild variant="outline">
              <Link to="/settings/exchange-accounts">
                Manage Exchange Policies
                <ArrowRight className="h-4 w-4 ml-2" />
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

interface PolicyItemProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  highlight?: boolean;
}

function PolicyItem({ label, value, icon, highlight }: PolicyItemProps) {
  return (
    <div className="rounded-lg border border-border/50 bg-card/50 p-4">
      <div className="flex items-center gap-2 text-muted-foreground mb-2">
        {icon}
        <span className="text-xs uppercase tracking-wider">{label}</span>
      </div>
      <p className={`text-lg font-semibold ${highlight ? "text-green-400" : ""}`}>{value}</p>
    </div>
  );
}





