import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { useStrategies } from "../../lib/api/hooks";
import { Strategy } from "../../lib/api/types";
import { cn } from "../../lib/utils";
import { Loader2, Settings, ExternalLink, Info } from "lucide-react";
import { Select } from "../../components/ui/select";

const getCategoryColor = (category: string) => {
  switch (category) {
    case "scalping":
      return "bg-blue-500/20 text-blue-300 border-blue-400/30";
    case "trend_following":
      return "bg-emerald-500/20 text-emerald-300 border-emerald-400/30";
    case "mean_reversion":
      return "bg-amber-500/20 text-amber-300 border-amber-400/30";
    case "session_based":
      return "bg-purple-500/20 text-purple-300 border-purple-400/30";
    default:
      return "bg-gray-500/20 text-gray-300 border-gray-400/30";
  }
};

const StrategyCard = ({ strategy }: { strategy: Strategy }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <Card className="border-white/5 bg-black/40">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <CardTitle className="text-lg font-semibold">{strategy.name}</CardTitle>
              <Badge className={cn("rounded-full px-2 py-1 text-xs", getCategoryColor(strategy.category))}>
                {strategy.category.replace(/_/g, " ")}
              </Badge>
              {strategy.inUseCount && strategy.inUseCount > 0 && (
                <Badge variant="outline" className="rounded-full">
                  {strategy.inUseCount} {strategy.inUseCount === 1 ? "profile" : "profiles"}
                </Badge>
              )}
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{strategy.description}</p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="gap-2"
          >
            <Settings className="h-4 w-4" />
            {isExpanded ? "Hide" : "Configure"}
          </Button>
        </div>
      </CardHeader>
      {isExpanded && (
        <CardContent className="space-y-6">
          {/* Strategy Usage */}
          {strategy.inUse && strategy.inUse.length > 0 && (
            <div>
              <Label className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
                Used In Profiles
              </Label>
              <div className="mt-2 space-y-2">
                {strategy.inUse.map((usage) => (
                  <div
                    key={usage.profileId}
                    className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2"
                  >
                    <div>
                      <p className="text-sm font-medium text-white">{usage.profileName}</p>
                      <p className="text-xs text-muted-foreground">{usage.environment}</p>
                    </div>
                    <Link to={`/dashboard/profile-editor/${usage.profileId}`}>
                      <Button variant="ghost" size="sm" className="gap-1">
                        View <ExternalLink className="h-3 w-3" />
                      </Button>
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Default Parameters */}
          <div>
            <Label className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
              Default Parameters
            </Label>
            <div className="mt-3 space-y-4">
              {Object.entries(strategy.defaultParams).map(([key, value]) => {
                const description = strategy.paramDescriptions[key] || "";
                const isBoolean = typeof value === "boolean";
                const isNumber = typeof value === "number";

                return (
                  <div key={key} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label htmlFor={`${strategy.id}-${key}`} className="text-sm font-medium">
                        {key.replace(/_/g, " ")}
                      </Label>
                      {description && (
                        <div className="group relative">
                          <Info className="h-3 w-3 text-muted-foreground" />
                          <div className="absolute right-0 top-6 z-10 hidden w-64 rounded-lg border border-white/10 bg-black/95 p-2 text-xs text-muted-foreground shadow-lg group-hover:block">
                            {description}
                          </div>
                        </div>
                      )}
                    </div>
                    {isBoolean ? (
                      <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 px-3 py-2">
                        <span className="text-sm text-muted-foreground">
                          {value ? "Enabled" : "Disabled"}
                        </span>
                        <Switch checked={value} disabled />
                      </div>
                    ) : isNumber ? (
                      <Input
                        id={`${strategy.id}-${key}`}
                        type="number"
                        value={value}
                        disabled
                        className="bg-white/5"
                      />
                    ) : (
                      <Input
                        id={`${strategy.id}-${key}`}
                        value={String(value)}
                        disabled
                        className="bg-white/5"
                      />
                    )}
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              These are default parameters. To customize, edit the profile that uses this strategy.
            </p>
          </div>
        </CardContent>
      )}
    </Card>
  );
};

export default function StrategyConfigPage() {
  const { data, isLoading, isFetching } = useStrategies();
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="ml-3 text-muted-foreground">Loading strategies...</p>
      </div>
    );
  }

  const strategies = data?.strategies || [];
  const categories = Array.from(new Set(strategies.map((s) => s.category)));

  // Filter strategies
  const filteredStrategies = strategies.filter((strategy) => {
    const matchesCategory = filterCategory === "all" || strategy.category === filterCategory;
    const matchesSearch =
      searchQuery === "" ||
      strategy.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      strategy.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      strategy.id.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Trading Strategies</h1>
          <p className="text-sm text-muted-foreground">
            Configure and manage trading strategies used by profiles
          </p>
        </div>
        <Link to="/profile-editor/new">
          <Button className="gap-2">
            <Settings className="h-4 w-4" /> Create Profile
          </Button>
        </Link>
      </div>

      {/* Filters */}
      <Card className="border-white/5 bg-black/40">
        <CardContent className="pt-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="search">Search Strategies</Label>
              <Input
                id="search"
                placeholder="Search by name, description, or ID..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="category">Filter by Category</Label>
              <Select
                id="category"
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
                options={[
                  { value: "all", label: "All Categories" },
                  ...categories.map((category) => ({
                    value: category,
                    label: category.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
                  })),
                ]}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Strategy List */}
      <div className="space-y-4">
        {filteredStrategies.length === 0 ? (
          <Card className="border-white/5 bg-black/40">
            <CardContent className="py-12 text-center">
              <p className="text-muted-foreground">
                {searchQuery || filterCategory !== "all"
                  ? "No strategies match your filters"
                  : "No strategies available"}
              </p>
            </CardContent>
          </Card>
        ) : (
          filteredStrategies.map((strategy) => (
            <StrategyCard key={strategy.id} strategy={strategy} />
          ))
        )}
      </div>

      {/* Summary Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
              Total Strategies
            </p>
            <p className="mt-2 text-3xl font-semibold">{strategies.length}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
              Active Strategies
            </p>
            <p className="mt-2 text-3xl font-semibold">
              {strategies.filter((s) => s.inUseCount && s.inUseCount > 0).length}
            </p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
              Categories
            </p>
            <p className="mt-2 text-3xl font-semibold">{categories.length}</p>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40">
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
              Total Profiles
            </p>
            <p className="mt-2 text-3xl font-semibold">
              {new Set(strategies.flatMap((s) => s.inUse?.map((u) => u.profileId) || [])).size}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

