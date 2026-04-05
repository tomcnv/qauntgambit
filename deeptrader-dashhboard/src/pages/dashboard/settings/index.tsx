import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { DashBar } from "../../../components/DashBar";
import {
  Search,
  User,
  Lock,
  Building2,
  Users,
  FileText,
  CreditCard,
  Settings2,
  Shield,
  Key,
  Bell,
  Database,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Activity,
  ChevronRight,
  Zap,
  Globe,
  DollarSign,
  ExternalLink,
  Code,
  Webhook,
} from "lucide-react";

import { Card, CardContent } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Badge } from "../../../components/ui/badge";
import { Separator } from "../../../components/ui/separator";
import { useTenantRiskPolicy } from "../../../lib/api/hooks";
import { cn } from "../../../lib/utils";

// ═══════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════

interface SettingsTile {
  id: string;
  title: string;
  description: string;
  icon: React.ElementType;
  path: string;
  keywords: string[];
  status?: {
    type: "success" | "warning" | "error" | "neutral";
    label: string;
  };
  group: "personal" | "account" | "product";
}

// ═══════════════════════════════════════════════════════════════
// SETTINGS TILES CONFIG
// ═══════════════════════════════════════════════════════════════

const SETTINGS_TILES: SettingsTile[] = [
  // Personal Settings
  {
    id: "profile",
    title: "Personal Details",
    description: "Your profile, password, and 2FA settings",
    icon: User,
    path: "/settings/security",
    keywords: ["profile", "password", "2fa", "two factor", "authentication", "personal"],
    status: { type: "warning", label: "2FA not enabled" },
    group: "personal",
  },
  {
    id: "preferences",
    title: "Communication Preferences",
    description: "Email and notification delivery preferences",
    icon: Bell,
    path: "/settings/notifications",
    keywords: ["email", "notifications", "preferences", "alerts", "communication"],
    group: "personal",
  },
  {
    id: "developer",
    title: "Developer Tools",
    description: "API keys, webhooks, and test tools",
    icon: Code,
    path: "/settings/developer",
    keywords: ["api", "keys", "webhooks", "developer", "integration", "test"],
    status: { type: "neutral", label: "No API keys" },
    group: "personal",
  },

  // Account Settings
  {
    id: "organization",
    title: "Organization",
    description: "Business name, timezone, and display settings",
    icon: Building2,
    path: "/settings/account",
    keywords: ["organization", "business", "company", "timezone", "currency", "branding"],
    status: { type: "success", label: "Configured" },
    group: "account",
  },
  {
    id: "team",
    title: "Team & Security",
    description: "Users, roles, permissions, and SSO",
    icon: Users,
    path: "/settings/team",
    keywords: ["team", "users", "roles", "permissions", "sso", "security"],
    status: { type: "neutral", label: "1 user" },
    group: "account",
  },
  {
    id: "compliance",
    title: "Compliance & Exports",
    description: "Audit exports, data retention, and configuration backups",
    icon: FileText,
    path: "/settings/compliance",
    keywords: ["compliance", "exports", "audit", "retention", "backup", "gdpr"],
    group: "account",
  },
  {
    id: "billing",
    title: "Billing & Plan",
    description: "Subscription, invoices, and payment methods",
    icon: CreditCard,
    path: "/settings/billing",
    keywords: ["billing", "plan", "subscription", "invoices", "payment", "upgrade"],
    status: { type: "success", label: "Pro Plan" },
    group: "account",
  },

  // Product Settings (Trading Platform)
  {
    id: "trading-defaults",
    title: "Trading Defaults",
    description: "Default execution behavior, sizing, and symbol universe",
    icon: Settings2,
    path: "/settings/trading",
    keywords: ["trading", "defaults", "execution", "sizing", "symbols", "timeframe"],
    status: { type: "success", label: "Configured" },
    group: "product",
  },
  {
    id: "risk-safety",
    title: "Risk & Safety Policy",
    description: "Tenant limits, kill switches, and live trading gates",
    icon: Shield,
    path: "/settings/risk",
    keywords: ["risk", "safety", "policy", "limits", "kill switch", "live trading"],
    status: { type: "warning", label: "Live blocked" },
    group: "product",
  },
  {
    id: "exchanges",
    title: "Exchanges & Keys",
    description: "API credentials, connection tests, and key rotation",
    icon: Key,
    path: "/settings/exchanges",
    keywords: ["exchanges", "api", "keys", "credentials", "okx", "binance", "bybit"],
    status: { type: "success", label: "2 connected" },
    group: "product",
  },
  {
    id: "notifications",
    title: "Notifications",
    description: "Alert channels, routing rules, and digests",
    icon: Bell,
    path: "/settings/notifications",
    keywords: ["notifications", "alerts", "slack", "telegram", "email", "webhook", "discord"],
    status: { type: "warning", label: "1 channel" },
    group: "product",
  },
  {
    id: "data-storage",
    title: "Data & Storage",
    description: "Retention policies, replay capture, and backtest defaults",
    icon: Database,
    path: "/settings/data",
    keywords: ["data", "storage", "retention", "replay", "backtest", "snapshots"],
    status: { type: "neutral", label: "90 day retention" },
    group: "product",
  },
  {
    id: "system-health",
    title: "System Health",
    description: "Exchange connectivity, runtime status, and health gates",
    icon: Activity,
    path: "/settings/system-health",
    keywords: ["health", "runtime", "status", "warmup", "data quality", "exchanges", "bots"],
    status: { type: "neutral", label: "Monitoring" },
    group: "product",
  },
  {
    id: "audit",
    title: "Audit Log",
    description: "Complete history of configuration changes",
    icon: FileText,
    path: "/audit",
    keywords: ["audit", "log", "history", "changes", "compliance"],
    group: "product",
  },
];

// ═══════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════

export default function SettingsHomePage() {
  const [searchQuery, setSearchQuery] = useState("");
  const { data: policyData } = useTenantRiskPolicy();
  const policy = policyData?.policy;

  // Filter tiles based on search
  const filteredTiles = useMemo(() => {
    if (!searchQuery.trim()) return SETTINGS_TILES;
    const query = searchQuery.toLowerCase();
    return SETTINGS_TILES.filter(
      (tile) =>
        tile.title.toLowerCase().includes(query) ||
        tile.description.toLowerCase().includes(query) ||
        tile.keywords.some((k) => k.includes(query))
    );
  }, [searchQuery]);

  // Group filtered tiles
  const personalTiles = filteredTiles.filter((t) => t.group === "personal");
  const accountTiles = filteredTiles.filter((t) => t.group === "account");
  const productTiles = filteredTiles.filter((t) => t.group === "product");

  // Policy blockers
  const policyIssues: string[] = [];
  if (!policy?.live_trading_enabled) policyIssues.push("Live trading is disabled");
  if (!policy?.max_daily_loss_pct) policyIssues.push("Daily loss limit not configured");
  // Add more checks as needed

  return (
    <>
      <DashBar />
      <div className="p-6 space-y-6 max-w-[1200px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Manage your account, trading configuration, and integrations
        </p>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search settings..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Policy Status Banner */}
      {policyIssues.length > 0 && (
        <div className="flex items-center justify-between gap-4 px-4 py-2.5 rounded-lg border border-amber-600/40 bg-amber-500/15">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <div className="flex items-center gap-2">
              <span className="font-medium text-amber-700 dark:text-amber-300">Action Required</span>
              <span className="text-sm text-amber-600 dark:text-amber-400">·</span>
              <span className="text-sm text-amber-600 dark:text-amber-400">
                {policyIssues.join(" · ")}
              </span>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 border-amber-600/40 text-amber-700 dark:text-amber-300 hover:bg-amber-500/20"
            asChild
          >
            <Link to="/settings/risk">Fix Issues</Link>
          </Button>
        </div>
      )}

      {/* Account Strip */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2 rounded-lg border border-border/50 bg-card text-sm">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">DeepTrader Ops</span>
          <Badge variant="outline" className="text-xs">Pro Plan</Badge>
        </div>
        <Separator orientation="vertical" className="h-4" />
        <div className="flex items-center gap-2 text-muted-foreground">
          <Zap className="h-4 w-4" />
          <span>Live Trading:</span>
          {policy?.live_trading_enabled ? (
            <Badge className="bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30">Enabled</Badge>
          ) : (
            <Badge className="bg-red-500/20 text-red-600 dark:text-red-400 border-red-500/30">Disabled</Badge>
          )}
        </div>
        <Separator orientation="vertical" className="h-4" />
        <div className="flex items-center gap-2 text-muted-foreground">
          <Globe className="h-4 w-4" />
          <span>America/New_York</span>
        </div>
        <Separator orientation="vertical" className="h-4" />
        <div className="flex items-center gap-2 text-muted-foreground">
          <DollarSign className="h-4 w-4" />
          <span>USD</span>
        </div>
        <div className="flex-1" />
        <Link
          to="/audit"
          className="text-primary hover:underline text-xs flex items-center gap-1"
        >
          View Audit Log <ExternalLink className="h-3 w-3" />
        </Link>
      </div>

      {/* Settings Groups */}
      {searchQuery && filteredTiles.length === 0 ? (
        <div className="text-center py-12">
          <Search className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
          <p className="text-muted-foreground">No settings found for "{searchQuery}"</p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Personal Settings */}
          {personalTiles.length > 0 && (
            <SettingsGroup title="Personal Settings" tiles={personalTiles} />
          )}

          {/* Account Settings */}
          {accountTiles.length > 0 && (
            <SettingsGroup title="Account Settings" tiles={accountTiles} />
          )}

          {/* Product Settings */}
          {productTiles.length > 0 && (
            <SettingsGroup title="Product Settings" tiles={productTiles} />
          )}
        </div>
      )}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// SETTINGS GROUP COMPONENT
// ═══════════════════════════════════════════════════════════════

function SettingsGroup({ title, tiles }: { title: string; tiles: SettingsTile[] }) {
  return (
    <div>
      <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider mb-4">
        {title}
      </h2>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {tiles.map((tile) => (
          <SettingsTileCard key={tile.id} tile={tile} />
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// SETTINGS TILE CARD COMPONENT
// ═══════════════════════════════════════════════════════════════

function SettingsTileCard({ tile }: { tile: SettingsTile }) {
  const Icon = tile.icon;

  const statusColors = {
    success: "bg-green-500/20 text-green-400 border-green-500/30",
    warning: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    error: "bg-red-500/20 text-red-400 border-red-500/30",
    neutral: "bg-muted text-muted-foreground border-border",
  };

  return (
    <Link to={tile.path}>
      <Card className="border-border/50 hover:border-primary/50 hover:bg-muted/30 transition-all group cursor-pointer h-full">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <div className="h-10 w-10 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0 group-hover:bg-primary/20 transition-colors">
              <Icon className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-medium group-hover:text-primary transition-colors">
                  {tile.title}
                </h3>
                <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 group-hover:text-primary transition-colors" />
              </div>
              <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">
                {tile.description}
              </p>
              {tile.status && (
                <Badge
                  className={cn("mt-2 text-xs", statusColors[tile.status.type])}
                >
                  {tile.status.label}
                </Badge>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
