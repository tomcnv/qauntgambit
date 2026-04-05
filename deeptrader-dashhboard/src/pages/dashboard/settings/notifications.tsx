import { useEffect, useMemo, useState } from "react";
import {
  Bell,
  Mail,
  MessageSquare,
  Send,
  Webhook,
  AlertTriangle,
  TestTube,
  Plus,
  Save,
  Loader2,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Switch } from "../../../components/ui/switch";
import { Badge } from "../../../components/ui/badge";
import SettingsPageLayout from "./layout";
import {
  useNotificationChannels,
  useCreateNotificationChannel,
  useUpdateNotificationChannel,
  useDeleteNotificationChannel,
  useNotificationRouting,
  useUpdateNotificationRouting,
} from "../../../lib/api/hooks";
import toast from "react-hot-toast";

interface NotificationChannel {
  id: string;
  type: "email" | "slack" | "discord" | "telegram" | "webhook";
  name: string;
  config: Record<string, string>;
  enabled: boolean;
  verified: boolean;
}

export default function NotificationsSettingsPage() {
  const [isSaving, setIsSaving] = useState(false);
  const { data: channelsData, isLoading: loadingChannels } = useNotificationChannels();
  const { data: routingData } = useNotificationRouting();
  const createChannel = useCreateNotificationChannel();
  const updateChannel = useUpdateNotificationChannel();
  const deleteChannel = useDeleteNotificationChannel();
  const updateRouting = useUpdateNotificationRouting();
  const [routing, setRouting] = useState<{ rules: { severity: string; channels: string[] }[] }>({ rules: [] });
  const channels = channelsData || [];

  useEffect(() => {
    if (routingData) setRouting(routingData);
  }, [routingData]);

  const severityRules = useMemo(() => {
    const map: Record<string, string[]> = {};
    routing.rules.forEach((r) => (map[r.severity] = r.channels));
    return map;
  }, [routing]);

  const saveRouting = async () => {
    try {
      await updateRouting.mutateAsync(routing);
      toast.success("Routing saved");
    } catch (err: any) {
      toast.error(err?.message || "Failed to save routing");
    }
  };

  return (
    <SettingsPageLayout
      title="Notifications"
      description="Alert channels, routing rules, and digests"
      actions={
        <div className="flex gap-2">
          <Button onClick={saveRouting} variant="outline" disabled={isSaving}>
            Save Routing
          </Button>
          <Button onClick={() => {}} disabled>
            {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
            Save Channels
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              Notification Channels
            </CardTitle>
            <CardDescription>Configure where alerts are delivered</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loadingChannels && <div className="text-sm text-muted-foreground">Loading channels...</div>}
            {channels.map((channel: any) => (
              <div
                key={channel.id}
                className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30"
              >
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-full bg-primary/20 flex items-center justify-center">
                    {channel.type === "email" && <Mail className="h-5 w-5 text-primary" />}
                    {channel.type === "slack" && <MessageSquare className="h-5 w-5 text-primary" />}
                    {channel.type === "webhook" && <Webhook className="h-5 w-5 text-primary" />}
                    {channel.type === "telegram" && <Send className="h-5 w-5 text-primary" />}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="font-medium">{channel.label || channel.type}</p>
                      <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">
                        {channel.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground capitalize">{channel.type}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm">
                    <TestTube className="h-4 w-4 mr-1" />
                    Test
                  </Button>
                  <Switch
                    checked={channel.enabled}
                    onChange={async (e) => {
                      try {
                        await updateChannel.mutateAsync({ id: channel.id, payload: { enabled: e.target.checked } });
                        toast.success("Channel updated");
                      } catch (err: any) {
                        toast.error(err?.message || "Failed to update channel");
                      }
                    }}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      try {
                        await deleteChannel.mutateAsync(channel.id);
                        toast.success("Channel removed");
                      } catch (err: any) {
                        toast.error(err?.message || "Failed to remove channel");
                      }
                    }}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            ))}

            <div className="grid gap-2 md:grid-cols-4">
              <Button
                variant="outline"
                className="h-auto py-3"
                onClick={async () => {
                  const email = window.prompt("Email address?");
                  if (!email) return;
                  try {
                    await createChannel.mutateAsync({ type: "email", label: email, config: { email } });
                    toast.success("Email channel added");
                  } catch (err: any) {
                    toast.error(err?.message || "Failed to add email");
                  }
                }}
              >
                <div className="flex flex-col items-center gap-1">
                  <Mail className="h-5 w-5" />
                  <span className="text-xs">Add Email</span>
                </div>
              </Button>
              <Button
                variant="outline"
                className="h-auto py-3"
                onClick={async () => {
                  const url = window.prompt("Slack webhook URL?");
                  if (!url) return;
                  try {
                    await createChannel.mutateAsync({ type: "slack", label: "Slack", config: { url } });
                    toast.success("Slack channel added");
                  } catch (err: any) {
                    toast.error(err?.message || "Failed to add Slack");
                  }
                }}
              >
                <div className="flex flex-col items-center gap-1">
                  <MessageSquare className="h-5 w-5" />
                  <span className="text-xs">Add Slack</span>
                </div>
              </Button>
              <Button
                variant="outline"
                className="h-auto py-3"
                onClick={async () => {
                  const token = window.prompt("Telegram bot token?");
                  const chatId = window.prompt("Telegram chat ID?");
                  if (!token || !chatId) return;
                  try {
                    await createChannel.mutateAsync({ type: "telegram", label: "Telegram", config: { token, chatId } });
                    toast.success("Telegram channel added");
                  } catch (err: any) {
                    toast.error(err?.message || "Failed to add Telegram");
                  }
                }}
              >
                <div className="flex flex-col items-center gap-1">
                  <Send className="h-5 w-5" />
                  <span className="text-xs">Add Telegram</span>
                </div>
              </Button>
              <Button
                variant="outline"
                className="h-auto py-3"
                onClick={async () => {
                  const url = window.prompt("Webhook URL?");
                  if (!url) return;
                  try {
                    await createChannel.mutateAsync({ type: "webhook", label: "Webhook", config: { url } });
                    toast.success("Webhook added");
                  } catch (err: any) {
                    toast.error(err?.message || "Failed to add webhook");
                  }
                }}
              >
                <div className="flex flex-col items-center gap-1">
                  <Webhook className="h-5 w-5" />
                  <span className="text-xs">Add Webhook</span>
                </div>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Alert Routing
            </CardTitle>
            <CardDescription>Configure which alerts go to which channels</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {["critical", "warning", "info"].map((sev) => (
                <div key={sev} className="p-4 rounded-lg border border-border bg-muted/30 space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium capitalize">{sev} alerts</p>
                      <p className="text-sm text-muted-foreground">
                        {sev === "critical"
                          ? "Incidents, safety triggers, hard errors"
                          : sev === "warning"
                          ? "Degraded data, order rejects, risk limits"
                          : "Daily digests, state changes"}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {channels.map((ch: any) => {
                      const selected = severityRules[sev]?.includes(ch.id);
                      return (
                        <Button
                          key={ch.id}
                          variant={selected ? "default" : "outline"}
                          size="sm"
                          onClick={() => {
                            const current = severityRules[sev] || [];
                            const next = selected ? current.filter((id) => id !== ch.id) : [...current, ch.id];
                            const nextRules = routing.rules.filter((r) => r.severity !== sev).concat([{ severity: sev, channels: next }]);
                            setRouting({ rules: nextRules });
                          }}
                        >
                          {ch.label || ch.type}
                        </Button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle>Digest Settings</CardTitle>
            <CardDescription>Configure summary reports</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div>
                <p className="font-medium">Daily Summary</p>
                <p className="text-sm text-muted-foreground">Receive a daily performance summary at 9:00 AM</p>
              </div>
              <Switch checked={true} onChange={() => {}} />
            </div>
            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div>
                <p className="font-medium">Weekly Report</p>
                <p className="text-sm text-muted-foreground">Receive a weekly analytics report on Mondays</p>
              </div>
              <Switch checked={false} onChange={() => {}} />
            </div>
          </CardContent>
        </Card>
      </div>
    </SettingsPageLayout>
  );
}

function AlertRoutingRow({
  label,
  severity,
}: {
  label: string;
  severity: "critical" | "high" | "medium" | "low";
}) {
  const severityColors = {
    critical: "bg-red-500/20 text-red-400 border-red-500/30",
    high: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    medium: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    low: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  };

  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted/30">
      <div className="flex items-center gap-3">
        <Badge className={severityColors[severity]}>{severity}</Badge>
        <span>{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
          <Mail className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0 opacity-30">
          <MessageSquare className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0 opacity-30">
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

