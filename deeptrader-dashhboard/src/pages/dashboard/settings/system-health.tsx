import { useMemo } from "react";
import SettingsPageLayout from "./layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Badge } from "../../../components/ui/badge";
import { Separator } from "../../../components/ui/separator";
import { Activity, AlertTriangle, CheckCircle2, XCircle, ShieldAlert, Wrench } from "lucide-react";
import { useHealthSnapshot, useBotInstances } from "../../../lib/api/hooks";
import { useExchangeAccounts } from "../../../lib/api/exchange-accounts-hooks";
import type { BotExchangeConfig, BotInstance } from "../../../lib/api/types";

type HealthBadge = "success" | "warning" | "default";

const statusToBadge = (status?: string): HealthBadge => {
  if (!status) return "default";
  const normalized = status.toLowerCase();
  if (["healthy", "ok", "ready", "running", "active"].includes(normalized)) return "success";
  if (["degraded", "warning", "warming", "starting"].includes(normalized)) return "warning";
  if (["critical", "error", "down", "failed", "stopped"].includes(normalized)) return "warning";
  return "default";
};

const formatTime = (value?: string) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const exchangeStatusLabel = (status?: string) => {
  if (!status) return "Unknown";
  return status.charAt(0).toUpperCase() + status.slice(1);
};

const exchangeStatusBadge = (status?: string): HealthBadge => {
  if (!status) return "default";
  if (status === "verified") return "success";
  if (status === "pending") return "warning";
  if (status === "error") return "warning";
  return "default";
};

const botConfigLabel = (config: BotExchangeConfig) => {
  const env = config.environment ? config.environment.toUpperCase() : "UNKNOWN";
  const exchange = config.exchange_account_label || config.exchange || "Exchange";
  return `${exchange} · ${env}`;
};

const healthStatusText = (status?: string | null) => {
  if (!status) return "Unknown";
  return status.toString().replace(/_/g, " ");
};

const ServiceStatusCard = ({ name, healthy, details }: { name: string; healthy: boolean; details?: string }) => (
  <div className="rounded-xl border border-border/50 bg-card/40 p-4">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        {healthy ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
        ) : (
          <XCircle className="h-5 w-5 text-red-400" />
        )}
        <div>
          <p className="font-semibold text-white">{name}</p>
          {details && <p className="text-xs text-muted-foreground">{details}</p>}
        </div>
      </div>
      <Badge variant={healthy ? "success" : "warning"}>{healthy ? "Healthy" : "Unhealthy"}</Badge>
    </div>
  </div>
);

export default function SystemHealthSettingsPage() {
  const { data: healthSnapshot, isFetching: loadingHealth } = useHealthSnapshot();
  const { data: exchangeAccounts = [], isLoading: loadingExchanges } = useExchangeAccounts();
  const { data: botInstancesData, isLoading: loadingBots } = useBotInstances(true);

  const serviceHealth = (healthSnapshot as any)?.serviceHealth;
  const componentDiagnostics = (healthSnapshot as any)?.componentDiagnostics;
  const positionGuardian = (healthSnapshot as any)?.position_guardian;
  const bots = botInstancesData?.bots ?? [];
  const exchangeMap = useMemo(() => {
    return new Map(exchangeAccounts.map((account) => [account.id, account]));
  }, [exchangeAccounts]);

  const botConfigs = useMemo(() => {
    const configs: Array<{ bot: BotInstance; config: BotExchangeConfig }> = [];
    bots.forEach((bot) => {
      bot.exchangeConfigs?.forEach((config) => {
        configs.push({ bot, config });
      });
    });
    return configs;
  }, [bots]);

  const issues = useMemo(() => {
    const items: Array<{
      title: string;
      detail: string;
      severity: "warning" | "critical";
      fix?: string;
    }> = [];
    if (serviceHealth && !serviceHealth.all_ready) {
      const missing = serviceHealth.missing || [];
      if (missing.length) {
        items.push({
          title: "Missing services",
          detail: missing.join(", "),
          severity: "critical",
          fix: "Start the missing services and re-check connectivity.",
        });
      }
      const downServices = Object.entries(serviceHealth.services || {})
        .filter(([, healthy]) => !healthy)
        .map(([name]) => name);
      if (downServices.length) {
        items.push({
          title: "Services down",
          detail: downServices.join(", "),
          severity: "warning",
          fix: "Inspect service logs and restart failed workers.",
        });
      }
    }
    if (componentDiagnostics) {
      const errorComponents = Object.entries(componentDiagnostics)
        .filter(([, data]) => (data?.error_count ?? 0) > 0 || data?.last_error)
        .slice(0, 6);
      errorComponents.forEach(([component, data]) => {
        items.push({
          title: `Component errors: ${component}`,
          detail: data?.last_error || "Recent errors detected.",
          severity: "warning",
          fix: "Check stack traces in logs and validate upstream data feeds.",
        });
      });
    }
    if (positionGuardian?.status === "misconfigured") {
      items.push({
        title: "Position guard misconfigured",
        detail: positionGuardian?.reason || "live_perp_guard_invalid",
        severity: "critical",
        fix: "Enable the live position guard and set a non-zero max age for open positions.",
      });
    }
    return items;
  }, [serviceHealth, componentDiagnostics, positionGuardian]);

  return (
    <SettingsPageLayout
      title="System Health"
      description="Monitor exchange connectivity, data readiness, and bot runtime status."
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Core Health
            </CardTitle>
            <CardDescription>Live snapshot of runtime services and data gates.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loadingHealth ? (
              <p className="text-sm text-muted-foreground">Loading health snapshot…</p>
            ) : serviceHealth ? (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  <Badge variant={serviceHealth.all_ready ? "success" : "warning"}>
                    {serviceHealth.all_ready ? "All services ready" : "Services degraded"}
                  </Badge>
                  {serviceHealth.missing?.length ? (
                    <Badge variant="warning">{serviceHealth.missing.length} missing</Badge>
                  ) : (
                    <Badge variant="success">No missing services</Badge>
                  )}
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {Object.entries(serviceHealth.services || {}).map(([service, healthy]) => (
                    <ServiceStatusCard
                      key={service}
                      name={service.replace(/_/g, " ")}
                      healthy={healthy as boolean}
                    />
                  ))}
                  {positionGuardian ? (
                    <ServiceStatusCard
                      name="position guardian"
                      healthy={positionGuardian.status === "running"}
                      details={
                        positionGuardian.status === "misconfigured"
                          ? `${positionGuardian.reason || "invalid_guard_policy"} · Max Age ${positionGuardian?.config?.maxAgeSec ?? 0}s`
                          : positionGuardian.status === "running"
                            ? `Max Age ${positionGuardian?.config?.maxAgeSec ?? 0}s`
                            : "Guardian not running"
                      }
                    />
                  ) : null}
                </div>
                {serviceHealth.missing?.length ? (
                  <div className="rounded-xl border border-red-400/30 bg-red-500/10 p-4 text-sm text-red-300">
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle className="h-4 w-4" />
                      <span className="font-semibold">Missing services</span>
                    </div>
                    <p>{serviceHealth.missing.join(", ")}</p>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No health snapshot available.</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" />
              Degraded Reasons
            </CardTitle>
            <CardDescription>What is unhealthy, examples, and suggested fixes.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {loadingHealth ? (
              <p className="text-sm text-muted-foreground">Analyzing health signals…</p>
            ) : issues.length ? (
              issues.map((issue, index) => (
                <div
                  key={`${issue.title}-${index}`}
                  className="rounded-xl border border-border/50 bg-card/40 p-4 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-amber-400" />
                      <p className="text-sm font-semibold text-white">{issue.title}</p>
                    </div>
                    <Badge variant={issue.severity === "critical" ? "warning" : "default"}>
                      {issue.severity === "critical" ? "Critical" : "Warning"}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{issue.detail}</p>
                  {issue.fix && (
                    <div className="flex items-start gap-2 text-xs text-muted-foreground">
                      <Wrench className="h-3.5 w-3.5 mt-0.5" />
                      <span>{issue.fix}</span>
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No active degradation signals detected.</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Exchange Health
            </CardTitle>
            <CardDescription>Credential status and account readiness.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {loadingExchanges ? (
              <p className="text-sm text-muted-foreground">Loading exchange accounts…</p>
            ) : exchangeAccounts.length ? (
              exchangeAccounts.map((account) => (
                <div
                  key={account.id}
                  className="flex flex-col gap-3 rounded-xl border border-border/50 bg-card/40 p-4 md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-white">{account.label}</p>
                      <Badge variant="outline" className="uppercase">
                        {account.venue}
                      </Badge>
                      <Badge variant="outline">{account.environment}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Last verified: {formatTime(account.last_verified_at)}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={exchangeStatusBadge(account.status)}>
                      {exchangeStatusLabel(account.status)}
                    </Badge>
                    {account.live_trading_enabled === false && (
                      <Badge variant="warning">Live blocked</Badge>
                    )}
                    {account.running_bot_count ? (
                      <Badge variant="success">{account.running_bot_count} running</Badge>
                    ) : (
                      <Badge variant="default">No running bots</Badge>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No exchange accounts configured.</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Bot Runtime Health
            </CardTitle>
            <CardDescription>Per-bot exchange configs and runtime heartbeat.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {loadingBots ? (
              <p className="text-sm text-muted-foreground">Loading bot status…</p>
            ) : botConfigs.length ? (
              botConfigs.map(({ bot, config }) => {
                const exchangeAccount = config.exchange_account_id
                  ? exchangeMap.get(config.exchange_account_id)
                  : undefined;
                const statusLabel = config.state || "unknown";
                const badge = statusToBadge(statusLabel);
                return (
                  <div
                    key={config.id}
                    className="flex flex-col gap-4 rounded-xl border border-border/50 bg-card/40 p-4 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-white">{bot.name}</p>
                      <p className="text-xs text-muted-foreground">{botConfigLabel(config)}</p>
                      <p className="text-xs text-muted-foreground">
                        Exchange account: {exchangeAccount?.label || "Unlinked"}
                      </p>
                      {config.last_error && (
                        <p className="text-xs text-red-300">Last error: {config.last_error}</p>
                      )}
                    </div>
                    <div className="space-y-2 text-right">
                      <Badge variant={badge}>{healthStatusText(statusLabel)}</Badge>
                      <div className="text-xs text-muted-foreground">
                        Last heartbeat: {formatTime(config.last_heartbeat_at)}
                      </div>
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-muted-foreground">No bots configured yet.</p>
            )}
          </CardContent>
        </Card>

        <Separator className="bg-border/50" />
        <div className="text-xs text-muted-foreground">
          Health data refreshes automatically. If exchange status shows verified but bot status is degraded, check warmup
          readiness and data quality signals.
        </div>
      </div>
    </SettingsPageLayout>
  );
}
