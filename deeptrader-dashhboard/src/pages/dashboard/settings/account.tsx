import { useEffect, useMemo, useState } from "react";
import { Building2, Loader2, Save, Users, Eye, Shield, UserPlus, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import SettingsPageLayout from "./layout";
import useAuthStore from "../../../store/auth-store";
import {
  useAccountSettings,
  useUpdateAccountSettings,
  useViewerAccounts,
  useCreateViewerAccount,
  useUpdateViewerAccount,
  useDeleteViewerAccount,
  useBotInstances,
} from "../../../lib/api/hooks";

const TIMEZONES = [
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "Eastern Time (ET)" },
  { value: "America/Chicago", label: "Central Time (CT)" },
  { value: "America/Los_Angeles", label: "Pacific Time (PT)" },
  { value: "Europe/London", label: "London (GMT/BST)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Asia/Bangkok", label: "Bangkok (ICT)" },
];

const CURRENCIES = [
  { value: "USD", label: "USD ($)" },
  { value: "USDT", label: "USDT" },
  { value: "EUR", label: "EUR (€)" },
  { value: "GBP", label: "GBP (£)" },
];

type ViewerFormState = {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  selectedBotKey: string;
};

const EMPTY_FORM: ViewerFormState = {
  email: "",
  password: "",
  firstName: "",
  lastName: "",
  selectedBotKey: "",
};

export default function AccountSettingsPage() {
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.role === "admin";

  const { data: accountSettings, isLoading: accountLoading } = useAccountSettings();
  const { data: viewerAccounts = [], isLoading: viewersLoading } = useViewerAccounts(isAdmin);
  const { data: botInstancesData } = useBotInstances(true);

  const updateAccountMutation = useUpdateAccountSettings();
  const createViewerMutation = useCreateViewerAccount();
  const updateViewerMutation = useUpdateViewerAccount();
  const deleteViewerMutation = useDeleteViewerAccount();

  const [settings, setSettings] = useState({
    orgName: "QuantGambit Ops",
    timezone: "UTC",
    baseCurrency: "USD",
    language: "en",
  });
  const [viewerForm, setViewerForm] = useState<ViewerFormState>(EMPTY_FORM);

  useEffect(() => {
    if (accountSettings) {
      setSettings({
        orgName: accountSettings.orgName || "QuantGambit Ops",
        timezone: accountSettings.timezone || "UTC",
        baseCurrency: accountSettings.baseCurrency || "USD",
        language: accountSettings.language || "en",
      });
    }
  }, [accountSettings]);

  const botOptions = useMemo(() => {
    return (botInstancesData?.bots || [])
      .map((bot) => {
        const activeConfig = bot.exchangeConfigs?.find((config) => config.is_active) || bot.exchangeConfigs?.[0];
        if (!activeConfig?.exchange_account_id) return null;
        const key = `${bot.id}:${activeConfig.exchange_account_id}`;
        return {
          key,
          botId: bot.id,
          botName: bot.name,
          exchangeAccountId: activeConfig.exchange_account_id,
          exchangeAccountName:
            activeConfig.exchange_account_label || activeConfig.exchange_account_venue || activeConfig.exchange || "Exchange",
          label: `${bot.name} • ${activeConfig.exchange_account_label || activeConfig.exchange || "Exchange"}`,
        };
      })
      .filter(Boolean) as Array<{
        key: string;
        botId: string;
        botName: string;
        exchangeAccountId: string;
        exchangeAccountName: string;
        label: string;
      }>;
  }, [botInstancesData]);

  const handleSaveAccount = async () => {
    try {
      await updateAccountMutation.mutateAsync(settings);
      toast.success("Account settings saved");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save account settings");
    }
  };

  const handleCreateViewer = async () => {
    const selectedBot = botOptions.find((option) => option.key === viewerForm.selectedBotKey);
    if (!selectedBot) {
      toast.error("Select a bot for the viewer");
      return;
    }
    try {
      await createViewerMutation.mutateAsync({
        email: viewerForm.email,
        password: viewerForm.password,
        firstName: viewerForm.firstName || undefined,
        lastName: viewerForm.lastName || undefined,
        botId: selectedBot.botId,
        botName: selectedBot.botName,
        exchangeAccountId: selectedBot.exchangeAccountId,
        exchangeAccountName: selectedBot.exchangeAccountName,
      });
      setViewerForm(EMPTY_FORM);
      toast.success("Viewer account created");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to create viewer");
    }
  };

  const toggleViewerActive = async (viewerId: string, isActive: boolean) => {
    try {
      await updateViewerMutation.mutateAsync({ viewerId, payload: { isActive: !isActive } });
      toast.success(isActive ? "Viewer disabled" : "Viewer re-enabled");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to update viewer");
    }
  };

  const removeViewer = async (viewerId: string) => {
    try {
      await deleteViewerMutation.mutateAsync(viewerId);
      toast.success("Viewer removed");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to remove viewer");
    }
  };

  return (
    <SettingsPageLayout
      title="Organization"
      description="Organization preferences and viewer-only sub-accounts"
      actions={
        <Button onClick={handleSaveAccount} disabled={updateAccountMutation.isPending || accountLoading}>
          {updateAccountMutation.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Save Changes
        </Button>
      }
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              Organization Profile
            </CardTitle>
            <CardDescription>Business name and display preferences for this tenant</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Organization Name</Label>
              <Input
                value={settings.orgName}
                onChange={(e) => setSettings((prev) => ({ ...prev, orgName: e.target.value }))}
                disabled={accountLoading}
              />
            </div>
            <div className="space-y-2">
              <Label>Timezone</Label>
              <Select
                value={settings.timezone}
                onChange={(e) => setSettings((prev) => ({ ...prev, timezone: e.target.value }))}
                options={TIMEZONES}
                disabled={accountLoading}
              />
            </div>
            <div className="space-y-2">
              <Label>Base Currency</Label>
              <Select
                value={settings.baseCurrency}
                onChange={(e) => setSettings((prev) => ({ ...prev, baseCurrency: e.target.value }))}
                options={CURRENCIES}
                disabled={accountLoading}
              />
            </div>
            <div className="space-y-2">
              <Label>Language</Label>
              <Input
                value={settings.language}
                onChange={(e) => setSettings((prev) => ({ ...prev, language: e.target.value }))}
                disabled={accountLoading}
              />
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              Viewer Accounts
            </CardTitle>
            <CardDescription>
              Create read-only sub-accounts that can only see one assigned bot’s KPIs, equity, trades, and positions.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {!isAdmin ? (
              <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
                Viewer account management is restricted to admin users.
              </div>
            ) : (
              <>
                <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                  <div className="mb-4 flex items-center gap-2">
                    <UserPlus className="h-4 w-4" />
                    <h3 className="font-medium">Add Viewer</h3>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    <div className="space-y-2">
                      <Label>Email</Label>
                      <Input
                        value={viewerForm.email}
                        onChange={(e) => setViewerForm((prev) => ({ ...prev, email: e.target.value }))}
                        placeholder="viewer@client.com"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Password</Label>
                      <Input
                        type="password"
                        value={viewerForm.password}
                        onChange={(e) => setViewerForm((prev) => ({ ...prev, password: e.target.value }))}
                        placeholder="Minimum 8 characters"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Assigned Bot</Label>
                      <Select
                        value={viewerForm.selectedBotKey}
                        onValueChange={(value) => setViewerForm((prev) => ({ ...prev, selectedBotKey: value }))}
                        options={[
                          { value: "", label: "Select a bot" },
                          ...botOptions.map((option) => ({ value: option.key, label: option.label })),
                        ]}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>First Name</Label>
                      <Input
                        value={viewerForm.firstName}
                        onChange={(e) => setViewerForm((prev) => ({ ...prev, firstName: e.target.value }))}
                        placeholder="Optional"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Last Name</Label>
                      <Input
                        value={viewerForm.lastName}
                        onChange={(e) => setViewerForm((prev) => ({ ...prev, lastName: e.target.value }))}
                        placeholder="Optional"
                      />
                    </div>
                  </div>
                  <div className="mt-4 flex justify-end">
                    <Button onClick={handleCreateViewer} disabled={createViewerMutation.isPending}>
                      {createViewerMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Eye className="mr-2 h-4 w-4" />
                      )}
                      Create Viewer Account
                    </Button>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Shield className="h-4 w-4" />
                    <h3 className="font-medium">Existing Viewers</h3>
                    {(viewersLoading || updateViewerMutation.isPending || deleteViewerMutation.isPending) && (
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    )}
                  </div>
                  {viewerAccounts.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
                      No viewer accounts yet.
                    </div>
                  ) : (
                    viewerAccounts.map((viewer) => (
                      <div
                        key={viewer.id}
                        className="flex flex-col gap-4 rounded-xl border border-border/60 bg-background p-4 lg:flex-row lg:items-center lg:justify-between"
                      >
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <p className="font-medium">{viewer.email}</p>
                            <Badge variant={viewer.isActive ? "default" : "secondary"}>
                              {viewer.isActive ? "Active" : "Disabled"}
                            </Badge>
                            <Badge variant="outline">Viewer</Badge>
                          </div>
                          <p className="text-sm text-muted-foreground">
                            {viewer.firstName || viewer.lastName
                              ? `${viewer.firstName || ""} ${viewer.lastName || ""}`.trim()
                              : viewer.username}
                          </p>
                          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                            <span>Bot: {viewer.viewerScope?.botName || viewer.viewerScope?.botId}</span>
                            <span>Exchange: {viewer.viewerScope?.exchangeAccountName || viewer.viewerScope?.exchangeAccountId}</span>
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            onClick={() => toggleViewerActive(viewer.id, viewer.isActive)}
                            disabled={updateViewerMutation.isPending}
                          >
                            <RefreshCw className="mr-2 h-4 w-4" />
                            {viewer.isActive ? "Disable" : "Re-enable"}
                          </Button>
                          <Button
                            variant="outline"
                            onClick={() => removeViewer(viewer.id)}
                            disabled={deleteViewerMutation.isPending}
                          >
                            Remove
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </SettingsPageLayout>
  );
}
