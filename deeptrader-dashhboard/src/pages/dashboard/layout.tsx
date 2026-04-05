import { useState, useEffect } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useCopilotStore } from "../../store/copilot-store";
import {
  Activity,
  AlertTriangle,
  Bot,
  ChevronRight,
  ChevronDown,
  Gauge,
  Settings,
  LogOut,
  Sun,
  Moon,
  TrendingUp,
  Shield,
  Bell,
  Menu,
  Play,
  Zap,
  Clock,
  History,
  Layers,
  Target,
  BarChart3,
  FileText,
  Database,
  FlaskConical,
  Globe,
  ListOrdered,
  ShieldAlert,
  ShieldCheck,
  Siren,
  RefreshCw,
  Building2,
  Book,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import { useTheme } from "../../components/theme-provider";
import useAuthStore from "../../store/auth-store";
import { useActiveModelInfo, useTradeProfile } from "../../lib/api/hooks";
import toast from "react-hot-toast";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { Avatar, AvatarFallback } from "../../components/ui/avatar";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "../../components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "../../components/ui/tooltip";
import { Separator } from "../../components/ui/separator";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../components/ui/collapsible";
import { CommandPalette } from "../../components/CommandPalette";
import { ScopeSelector, ScopeBadge } from "../../components/scope-selector";

// ============================================================================
// NAVIGATION STRUCTURE - Clear IA based on mental model
// ============================================================================

const NAV_GROUPS = [
  {
    id: "trading",
    label: "Trading",
    icon: TrendingUp,
    description: "What's happening right now",
    items: [
      { label: "Overview", icon: Gauge, path: "/", description: "Mission control + fleet" },
      { label: "Live", icon: Activity, path: "/live", description: "Active bot status & controls" },
      { label: "Orders & Fills", icon: ListOrdered, path: "/orders", description: "Fill rate, latency, rejects" },
      { label: "Positions", icon: Target, path: "/positions", description: "Open positions & exposure" },
      { label: "Trade History", icon: History, path: "/history", description: "All trades, filterable" },
    ],
  },
  {
    id: "risk",
    label: "Risk",
    icon: Shield,
    description: "Am I safe right now?",
    items: [
      { label: "Limits & Guardrails", icon: ShieldCheck, path: "/risk/limits", description: "Live controls" },
      { label: "Exposure", icon: Target, path: "/risk/exposure", description: "Current & historical" },
      { label: "VaR & Stress Tests", icon: ShieldAlert, path: "/risk/metrics", description: "VaR, ES, scenarios" },
      { label: "Incidents", icon: Siren, path: "/risk/incidents", description: "Breaches & post-mortems" },
    ],
  },
  {
    id: "analysis",
    label: "Analysis",
    icon: BarChart3,
    description: "Why it's happening",
    items: [
      { label: "Pipeline Health", icon: Activity, path: "/pipeline-health", description: "Engine layers & latency" },
      { label: "Replay Studio", icon: Play, path: "/analysis/replay", description: "Decision forensics & replay" },
      { label: "Market Context", icon: Globe, path: "/market-context", description: "Regime & conditions" },
      { label: "Signals", icon: Zap, path: "/signals", description: "Signal health & features" },
      { label: "Execution", icon: Clock, path: "/execution", description: "TCA, slippage, latency" },
    ],
  },
  {
    id: "research",
    label: "Research",
    icon: FlaskConical,
    description: "Offline experimentation",
    items: [
      { label: "Backtesting", icon: FlaskConical, path: "/backtesting", description: "Run & analyze backtests" },
      { label: "Model Training", icon: Activity, path: "/analysis/model-training", description: "Train & promote ONNX models" },
      { label: "Data Quality", icon: Database, path: "/data-quality", description: "Feed health & gaps" },
    ],
  },
  {
    id: "system",
    label: "System",
    icon: Settings,
    description: "Controls & governance",
    items: [
      { label: "Exchange Accounts", icon: Building2, path: "/exchange-accounts", description: "Venue connections & risk pools" },
      { label: "Bot Management", icon: Bot, path: "/bot-management", description: "Fleet ops & bot builder" },
      { label: "Profiles", icon: Layers, path: "/profiles", description: "Strategy profiles" },
      { label: "Settings", icon: Settings, path: "/settings", description: "Global configuration" },
      { label: "Runtime Config", icon: SlidersHorizontal, path: "/settings/runtime-config", description: "Live knobs (golden source)" },
      { label: "Audit Log", icon: FileText, path: "/audit", description: "Change history" },
      { label: "Documentation", icon: Book, path: "/docs", description: "Platform docs & guides" },
    ],
  },
];

// Flatten for page title lookup
const ALL_NAV_ITEMS = NAV_GROUPS.flatMap(g => g.items);

// ============================================================================
// COMPONENTS
// ============================================================================

// BotSelector removed - replaced with ScopeSelector (exchange-first architecture)

function NavGroup({ 
  group, 
  isCollapsed,
  isExpanded,
  onToggle,
}: { 
  group: typeof NAV_GROUPS[0]; 
  isCollapsed: boolean;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const location = useLocation();
  const isActive = group.items.some(item => 
    location.pathname === item.path || 
    (item.path !== "/" && location.pathname.startsWith(item.path))
  );

  if (isCollapsed) {
    return (
      <div className="space-y-1">
        {group.items.map((item) => {
          const itemActive = location.pathname === item.path || 
            (item.path !== "/" && location.pathname.startsWith(item.path));
          return (
            <Tooltip key={item.path}>
              <TooltipTrigger asChild>
                <NavLink to={item.path}>
                  <div className={cn(
                    "relative flex h-10 w-10 items-center justify-center rounded-r-xl transition-all",
                    itemActive
                      ? "bg-primary/10 text-primary before:absolute before:left-0 before:top-1 before:bottom-1 before:w-1 before:rounded-full before:bg-primary dark:bg-[hsl(230_35%_18%)] dark:text-white dark:before:bg-[hsl(250_90%_65%)]"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  )}>
                    <item.icon className="h-5 w-5" />
                  </div>
                </NavLink>
              </TooltipTrigger>
              <TooltipContent side="right" className="flex flex-col gap-0.5">
                <span className="font-medium">{item.label}</span>
                <span className="text-xs text-muted-foreground">{item.description}</span>
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    );
  }

  return (
    <Collapsible open={isExpanded} onOpenChange={onToggle}>
      <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors">
        <span>{group.label}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", isExpanded && "rotate-180")} />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-0.5 pt-1">
        {group.items.map((item) => {
          const itemActive = location.pathname === item.path || 
            (item.path !== "/" && location.pathname.startsWith(item.path));
          return (
            <NavLink key={item.path} to={item.path}>
              <div className={cn(
                "relative flex items-center gap-3 rounded-r-xl py-2.5 pl-4 pr-3 text-sm transition-all",
                itemActive
                  ? "bg-primary/10 text-primary before:absolute before:left-0 before:top-1 before:bottom-1 before:w-1 before:rounded-full before:bg-primary dark:bg-[hsl(230_35%_18%)] dark:text-white dark:before:bg-[hsl(250_90%_65%)]"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}>
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </div>
            </NavLink>
          );
        })}
      </CollapsibleContent>
    </Collapsible>
  );
}

// TradingHeader and StatusIndicator removed - replaced by RunBar component on trading pages

// ============================================================================
// MAIN LAYOUT
// ============================================================================

export default function DashboardLayout() {
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);
  const { data: tradeProfile } = useTradeProfile();
  const { data: activeModelInfo } = useActiveModelInfo();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(["trading", "risk", "analysis", "research"]));

  // Check if user has verified credentials for settings sheet
  const hasVerifiedCredential = Boolean(tradeProfile?.active_credential_id) && tradeProfile?.credential_status === "verified";

  // User info
  const initials = user
    ? (user.firstName || user.lastName
        ? `${user.firstName?.[0] ?? ""}${user.lastName?.[0] ?? ""}`.trim()
        : user.username?.slice(0, 2)?.toUpperCase() || "DT")
    : "DT";

  const toggleGroup = (groupId: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  // Reset scroll position on route change
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname]);

  // Sync current page path to copilot store for page-aware context
  const setCurrentPagePath = useCopilotStore((s) => s.setCurrentPagePath);
  useEffect(() => {
    setCurrentPagePath(location.pathname);
  }, [location.pathname, setCurrentPagePath]);

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex flex-col h-screen bg-background">
        {/* ============================================================ */}
        {/* TOP HEADER - Spans full width (both columns) */}
        {/* ============================================================ */}
        <header className={cn(
          "relative flex h-14 items-center justify-between px-4 lg:px-6 shrink-0 backdrop-blur-2xl border-b transition-colors overflow-hidden",
          // Background gradient based on theme
          theme === "dark" 
            ? "bg-gradient-to-r from-slate-950 via-slate-900 to-slate-950 border-slate-700/50 shadow-xl shadow-black/50 backdrop-blur-xl"
            : "bg-gradient-to-r from-slate-100 via-white to-slate-100 border-slate-200 shadow-sm"
        )}>
          {/* Subtle color accent - very subtle primary tint */}
          <div className={cn(
            "absolute inset-0 bg-gradient-to-r via-transparent pointer-events-none",
            theme === "dark"
              ? "from-blue-500/[0.06] via-purple-500/[0.04] to-blue-500/[0.06]"
              : "from-primary/[0.04] to-violet-500/[0.04]"
          )} />
          {/* Top highlight line - creates depth */}
          <div className={cn(
            "absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent to-transparent",
            theme === "dark" ? "via-white/20" : "via-slate-300/50"
          )} />
          {/* Bottom accent line - primary colored */}
          <div className={cn(
            "absolute bottom-0 left-1/2 -translate-x-1/2 w-3/4 h-px bg-gradient-to-r from-transparent to-transparent",
            theme === "dark" ? "via-primary/60" : "via-primary/40"
          )} />
          {/* Corner accents - very subtle */}
          <div className={cn(
            "absolute top-0 left-0 w-32 h-full bg-gradient-to-r to-transparent pointer-events-none",
            theme === "dark" ? "from-primary/[0.08]" : "from-primary/[0.03]"
          )} />
          <div className={cn(
            "absolute top-0 right-0 w-32 h-full bg-gradient-to-l to-transparent pointer-events-none",
            theme === "dark" ? "from-violet-500/[0.08]" : "from-violet-500/[0.03]"
          )} />
          {/* Left: Logo + Mobile menu */}
          <div className="relative z-10 flex items-center gap-3">
            <Button 
              variant="ghost" 
              size="icon" 
              className={cn(
                "lg:hidden h-8 w-8",
                theme === "dark" 
                  ? "text-slate-300 hover:text-white hover:bg-white/10"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/50"
              )}
              onClick={() => setMobileMenuOpen(true)}
            >
              <Menu className="h-4 w-4" />
            </Button>
            <Link to="/" className="flex items-center gap-2.5 hover:opacity-90 transition-opacity group">
              {/* Logo adapts to theme */}
              <img 
                src={theme === "dark" ? "/quantgambit-dark.png" : "/quantgambit-light.png"}
                alt="QuantGambit" 
                className="h-10 w-auto transition-all drop-shadow-sm group-hover:drop-shadow-md"
              />
            </Link>
          </div>

          {/* Center: Search bar */}
          <div className="relative z-10 flex-1 max-w-md mx-4 hidden sm:block">
            <div className="relative group cursor-pointer" onClick={() => setCommandPaletteOpen(true)}>
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 group-focus-within:text-primary transition-colors" />
              <Input
                type="search"
                placeholder="Search symbols, trades, settings..."
                readOnly
                onFocus={() => setCommandPaletteOpen(true)}
                className={cn(
                  "w-full pl-9 h-9 rounded-xl transition-all cursor-pointer",
                  theme === "dark"
                    ? "bg-white/10 border-white/10 text-white placeholder:text-slate-400 focus:border-primary focus:bg-white/15 focus:ring-2 focus:ring-primary/30"
                    : "bg-slate-100 border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-primary focus:bg-white focus:ring-2 focus:ring-primary/20"
                )}
              />
              {/* Subtle keyboard hint */}
              <div className="absolute right-3 top-1/2 -translate-y-1/2 hidden lg:flex items-center gap-1 text-[10px] font-mono pointer-events-none group-focus-within:opacity-0 transition-opacity text-slate-400">
                <kbd className={cn(
                  "px-1.5 py-0.5 rounded",
                  theme === "dark" 
                    ? "bg-white/10 border border-white/20 text-slate-300"
                    : "bg-slate-200 border border-slate-300 text-slate-500"
                )}>⌘</kbd>
                <kbd className={cn(
                  "px-1.5 py-0.5 rounded",
                  theme === "dark" 
                    ? "bg-white/10 border border-white/20 text-slate-300"
                    : "bg-slate-200 border border-slate-300 text-slate-500"
                )}>K</kbd>
              </div>
            </div>
          </div>

          {/* Right: Notifications, Settings, User */}
          <div className="relative z-10 flex items-center gap-1">
            <Button
              variant="ghost"
              className={cn(
                "hidden xl:flex h-8 px-2 rounded-lg text-xs font-mono",
                theme === "dark"
                  ? "text-slate-300 hover:text-white hover:bg-white/10"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/50"
              )}
              onClick={() => navigate("/analysis/model-training")}
              title={activeModelInfo?.model_file || "No active model info"}
            >
              <span className="mr-1 text-muted-foreground">Model</span>
              <Badge variant="outline" className="h-5 px-1.5 font-mono text-[10px]">
                {String(activeModelInfo?.model_file || "unknown").replace("prediction_baseline_", "").replace(".onnx", "")}
              </Badge>
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  className={cn(
                    "relative h-9 w-9 rounded-xl transition-colors",
                    theme === "dark"
                      ? "text-slate-300 hover:text-white hover:bg-white/10"
                      : "text-slate-500 hover:text-slate-900 hover:bg-slate-200/50"
                  )}
                >
                  <Bell className="h-4 w-4" />
                  <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-red-500 animate-pulse shadow-[0_0_8px_rgba(239,68,68,0.5)]" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Notifications</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  className={cn(
                    "h-9 w-9 rounded-xl transition-colors",
                    theme === "dark"
                      ? "text-slate-300 hover:text-white hover:bg-white/10"
                      : "text-slate-500 hover:text-slate-900 hover:bg-slate-200/50"
                  )}
                  onClick={() => navigate("/settings")}
                >
                  <Settings className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Settings</TooltipContent>
            </Tooltip>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  className={cn(
                    "rounded-full h-9 w-9 ml-1",
                    theme === "dark" ? "hover:bg-white/10" : "hover:bg-slate-200/50"
                  )}
                >
                  <Avatar className={cn(
                    "h-7 w-7 ring-2",
                    theme === "dark"
                      ? "ring-primary/50 shadow-lg shadow-primary/20"
                      : "ring-primary/40 shadow-md"
                  )}>
                    <AvatarFallback className="text-xs bg-gradient-to-br from-primary to-violet-500 text-white font-semibold">{initials}</AvatarFallback>
                  </Avatar>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <div className="flex flex-col space-y-1">
                    <p className="text-sm font-medium">{user?.email || "User"}</p>
                    <p className="text-xs text-muted-foreground">{hasVerifiedCredential ? "Exchange Connected" : "No Exchange"}</p>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/settings")}>
                  <Settings className="mr-2 h-4 w-4" />
                  Settings
                </DropdownMenuItem>
                <DropdownMenuItem onClick={toggleTheme}>
                  {theme === "dark" ? <Sun className="mr-2 h-4 w-4" /> : <Moon className="mr-2 h-4 w-4" />}
                  {theme === "dark" ? "Light Mode" : "Dark Mode"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout} className="text-red-500">
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* ============================================================ */}
        {/* MAIN AREA - Sidebar + Content */}
        {/* ============================================================ */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <aside className="hidden lg:flex flex-col border-r bg-card/50 backdrop-blur-sm w-[260px] shrink-0">
            {/* Scope Selector - Exchange Account First */}
            <div className="p-3">
              <ScopeSelector />
            </div>

            {/* Navigation */}
            <ScrollArea className="flex-1 py-3">
              <div className="space-y-4 px-3">
                {NAV_GROUPS.map((group) => (
                  <NavGroup 
                    key={group.id} 
                    group={group} 
                    isCollapsed={false}
                    isExpanded={expandedGroups.has(group.id)}
                    onToggle={() => toggleGroup(group.id)}
                  />
                ))}
              </div>
            </ScrollArea>
          </aside>

          {/* Main content */}
          <main className="flex flex-1 flex-col overflow-auto bg-background">
            <Outlet />
          </main>
        </div>
        {/* End of sidebar + content flex container */}

        {/* Settings Sheet */}
        <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
          <SheetContent className="w-full sm:max-w-md overflow-y-auto">
            <SheetHeader>
              <SheetTitle>Settings</SheetTitle>
              <SheetDescription>Configure your trading preferences</SheetDescription>
            </SheetHeader>
            <div className="mt-6 space-y-6">
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Exchange</h3>
                <div className="rounded-xl border bg-card p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={cn("h-10 w-10 rounded-xl flex items-center justify-center", hasVerifiedCredential ? "bg-emerald-500/10" : "bg-muted")}>
                        {hasVerifiedCredential ? <Zap className="h-5 w-5 text-emerald-500" /> : <AlertTriangle className="h-5 w-5 text-muted-foreground" />}
                      </div>
                      <div>
                        <p className="text-sm font-medium">{tradeProfile?.credential_exchange?.toUpperCase() || "Not Connected"}</p>
                        <p className="text-xs text-muted-foreground">{hasVerifiedCredential ? "API keys verified" : "Configure API keys"}</p>
                      </div>
                    </div>
                    <Link to="/bot-management">
                      <Button variant="outline" size="sm" onClick={() => setSettingsOpen(false)}>Configure</Button>
                    </Link>
                  </div>
                </div>
              </div>

              {hasVerifiedCredential && (
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Capital</h3>
                  <div className="rounded-xl border bg-card p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Available</span>
                      <span className="text-sm font-mono font-medium">${((tradeProfile as any)?.credential_trading_capital || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                    </div>
                    <Separator />
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">Exchange Balance</span>
                      <span className="text-sm font-mono font-medium">${((tradeProfile as any)?.credential_exchange_balance || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                    </div>
                  </div>
                </div>
              )}

              <div className="space-y-3">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Appearance</h3>
                <div className="grid grid-cols-2 gap-2">
                  <Button variant={theme === "light" ? "default" : "outline"} size="sm" onClick={() => theme === "dark" && toggleTheme()} className="h-12">
                    <Sun className="mr-2 h-4 w-4" />Light
                  </Button>
                  <Button variant={theme === "dark" ? "default" : "outline"} size="sm" onClick={() => theme === "light" && toggleTheme()} className="h-12">
                    <Moon className="mr-2 h-4 w-4" />Dark
                  </Button>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Quick Links</h3>
                <div className="space-y-1">
                  <Link to="/risk/limits" onClick={() => setSettingsOpen(false)}>
                    <Button variant="ghost" className="w-full justify-start"><Shield className="mr-2 h-4 w-4" />Risk Settings</Button>
                  </Link>
                  <Link to="/history" onClick={() => setSettingsOpen(false)}>
                    <Button variant="ghost" className="w-full justify-start"><History className="mr-2 h-4 w-4" />Trade History</Button>
                  </Link>
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>

        {/* Mobile menu sheet */}
        <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
          <SheetContent side="left" className="w-[300px] p-0">
            <div className="flex h-14 items-center border-b px-4">
              <div className="flex items-center gap-2.5">
                <img 
                  src={theme === "dark" ? "/quantgambit-dark.png" : "/quantgambit-light.png"} 
                  alt="QuantGambit" 
                  className="h-8 w-auto" 
                />
              </div>
            </div>
            <div className="border-b p-3">
              <ScopeSelector />
            </div>
            <ScrollArea className="flex-1 py-3 px-3">
              <div className="space-y-4">
                {NAV_GROUPS.map((group) => (
                  <NavGroup 
                    key={group.id} 
                    group={group} 
                    isCollapsed={false}
                    isExpanded={expandedGroups.has(group.id)}
                    onToggle={() => toggleGroup(group.id)}
                  />
                ))}
              </div>
            </ScrollArea>
          </SheetContent>
        </Sheet>

        {/* Command Palette (⌘K) */}
        <CommandPalette open={commandPaletteOpen} onOpenChange={setCommandPaletteOpen} />
      </div>
    </TooltipProvider>
  );
}
