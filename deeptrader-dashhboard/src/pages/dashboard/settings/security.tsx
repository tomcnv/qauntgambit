import { useEffect, useState } from "react";
import { Lock, Smartphone, KeyRound, Shield, Plus, Save, Loader2, Trash2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Switch } from "../../../components/ui/switch";
import { Badge } from "../../../components/ui/badge";
import { cn } from "../../../lib/utils";
import SettingsPageLayout from "./layout";
import {
  useSecuritySettings,
  useUpdateSecuritySettings,
  useApiKeys,
  useCreateApiKey,
  useDeleteApiKey,
  useValidateApiKey,
  useValidateTwoFactor,
  useEnrollTwoFactor,
  useConfirmTwoFactor,
  useDisableTwoFactor,
  useGenerateBackupCodes,
} from "../../../lib/api/hooks";
import toast from "react-hot-toast";

export default function SecuritySettingsPage() {
  const { data: securityData, isLoading: loadingSecurity } = useSecuritySettings();
  const updateSecurity = useUpdateSecuritySettings();
  const { data: apiKeys } = useApiKeys();
  const createKey = useCreateApiKey();
  const deleteKey = useDeleteApiKey();
  const validateKey = useValidateApiKey();
  const validate2fa = useValidateTwoFactor();
  const enroll2fa = useEnrollTwoFactor();
  const confirm2fa = useConfirmTwoFactor();
  const disable2fa = useDisableTwoFactor();
  const generateBackupCodes = useGenerateBackupCodes();
  const [isSaving, setIsSaving] = useState(false);
  const [settings, setSettings] = useState({
    twoFactorEnabled: false,
    sessionTimeout: 60,
    requireTwoFactorForLive: true,
    lastValidatedAt: null as string | null,
  });
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [qrData, setQrData] = useState<{ otpauthUrl: string; qr: string; secret: string } | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);

  useEffect(() => {
    if (securityData) {
      setSettings({
        twoFactorEnabled: securityData.twoFactorEnabled ?? false,
        sessionTimeout: securityData.sessionTimeout ?? 60,
        requireTwoFactorForLive: securityData.requireTwoFactorForLive ?? true,
        lastValidatedAt: (securityData as any).lastValidatedAt ?? null,
      });
    }
  }, [securityData]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await updateSecurity.mutateAsync(settings);
      toast.success("Security settings saved");
    } catch (err: any) {
      toast.error(err?.message || "Failed to save security settings");
    } finally {
      setIsSaving(false);
    }
  };

  const handleCreateKey = async () => {
    try {
      const key = await createKey.mutateAsync(newKeyLabel || "API Key");
      setNewKeyValue(key.apiKey || null);
      setNewKeyLabel("");
      toast.success("API key created. Copy it now; it is shown only once.");
    } catch (err: any) {
      toast.error(err?.message || "Failed to create API key");
    }
  };

  const handleDeleteKey = async (id: string) => {
    try {
      await deleteKey.mutateAsync(id);
      toast.success("API key deleted");
    } catch (err: any) {
      toast.error(err?.message || "Failed to delete key");
    }
  };

  return (
    <SettingsPageLayout
      title="Security"
      description="Authentication, sessions, and access controls"
      actions={
        <Button onClick={handleSave} disabled={isSaving || loadingSecurity}>
          {isSaving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
          Save Changes
        </Button>
      }
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lock className="h-5 w-5" />
              Authentication
            </CardTitle>
            <CardDescription>Account security and session management</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "h-10 w-10 rounded-full flex items-center justify-center",
                    settings.twoFactorEnabled ? "bg-green-500/20" : "bg-muted"
                  )}
                >
                  <Smartphone
                    className={cn(
                      "h-5 w-5",
                      settings.twoFactorEnabled ? "text-green-400" : "text-muted-foreground"
                    )}
                  />
                </div>
                <div>
                  <p className="font-medium">Two-Factor Authentication</p>
                  <p className="text-sm text-muted-foreground">
                    {settings.twoFactorEnabled
                      ? "2FA is enabled on your account"
                      : "Add an extra layer of security"}
                  </p>
                </div>
              </div>
              <Button variant={settings.twoFactorEnabled ? "outline" : "default"}>
                {settings.twoFactorEnabled ? "Manage" : "Enable 2FA"}
              </Button>
            </div>

            <div className="space-y-2">
              <Label>Session Timeout (minutes)</Label>
              <Select
                value={String(settings.sessionTimeout)}
                onChange={(e) => setSettings({ ...settings, sessionTimeout: parseInt(e.target.value) })}
                options={[
                  { value: "15", label: "15 minutes" },
                  { value: "30", label: "30 minutes" },
                  { value: "60", label: "1 hour" },
                  { value: "240", label: "4 hours" },
                  { value: "1440", label: "24 hours" },
                ]}
              />
            </div>

            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div>
                <p className="font-medium">Require 2FA for Live Trading</p>
                <p className="text-sm text-muted-foreground">
                  2FA must be enabled before live trading is allowed
                </p>
              </div>
              <Switch
                checked={settings.requireTwoFactorForLive}
                onChange={(e) => setSettings({ ...settings, requireTwoFactorForLive: e.target.checked })}
              />
            </div>

            <div className="space-y-2">
              <Label>Validate 2FA Code</Label>
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
                  placeholder="Enter current 2FA code"
                  value={twoFactorCode}
                  onChange={(e) => setTwoFactorCode(e.target.value)}
                />
                <Button
                  variant="outline"
                  onClick={async () => {
                    if (!twoFactorCode.trim()) return;
                    try {
                      const res = await validate2fa.mutateAsync(twoFactorCode.trim());
                      toast.success(res.valid ? "2FA validated" : "Invalid code");
                    } catch (err: any) {
                      toast.error(err?.message || "2FA validation failed");
                    }
                  }}
                  disabled={!twoFactorCode}
                >
                  Validate
                </Button>
              </div>
              {settings.lastValidatedAt && (
                <p className="text-xs text-muted-foreground">
                  Last validated: {new Date(settings.lastValidatedAt).toLocaleString()}
                </p>
              )}
            </div>

            <div className="space-y-3">
              <Label>Enroll / Manage TOTP</Label>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={async () => {
                    try {
                      const res = await enroll2fa.mutateAsync();
                      setQrData(res);
                      toast.success("Scan the QR with your authenticator app");
                    } catch (err: any) {
                      toast.error(err?.message || "Failed to start enrollment");
                    }
                  }}
                >
                  Get QR
                </Button>
                <Button
                  variant="default"
                  onClick={async () => {
                    if (!twoFactorCode.trim()) {
                      toast.error("Enter the code from your app");
                      return;
                    }
                    try {
                      await confirm2fa.mutateAsync(twoFactorCode.trim());
                      toast.success("2FA enabled");
                      setQrData(null);
                    } catch (err: any) {
                      toast.error(err?.message || "Failed to confirm 2FA");
                    }
                  }}
                >
                  Confirm
                </Button>
                <Button
                  variant="ghost"
                  onClick={async () => {
                    try {
                      await disable2fa.mutateAsync();
                      toast.success("2FA disabled");
                      setQrData(null);
                      setBackupCodes(null);
                    } catch (err: any) {
                      toast.error(err?.message || "Failed to disable 2FA");
                    }
                  }}
                >
                  Disable
                </Button>
                <Button
                  variant="outline"
                  onClick={async () => {
                    try {
                      const codes = await generateBackupCodes.mutateAsync();
                      setBackupCodes(codes);
                      toast.success("Backup codes regenerated. Save them securely.");
                    } catch (err: any) {
                      toast.error(err?.message || "Failed to generate backup codes");
                    }
                  }}
                  disabled={!settings.twoFactorEnabled}
                >
                  Backup Codes
                </Button>
              </div>
              {qrData && (
                <div className="p-3 rounded-md border border-border bg-muted/30 space-y-2">
                  <p className="text-sm font-medium">Scan this QR with your authenticator</p>
                  <img src={qrData.qr} alt="TOTP QR" className="w-48 h-48" />
                  <p className="text-xs text-muted-foreground break-all">Secret: {qrData.secret}</p>
                </div>
              )}
              {backupCodes && (
                <div className="p-3 rounded-md border border-border bg-muted/30 space-y-2">
                  <p className="text-sm font-medium">Backup codes (one-time, store safely):</p>
                  <div className="grid grid-cols-2 gap-2 text-sm font-mono">
                    {backupCodes.map((c) => (
                      <span key={c}>{c}</span>
                    ))}
                  </div>
                </div>
              )}
              {settings.requireTwoFactorForLive && (
                <div className="p-3 rounded-md border border-amber-500/40 bg-amber-500/10 text-sm text-amber-700">
                  Live trading requires recent 2FA validation. Ensure codes are current.
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="h-5 w-5" />
              API Access
            </CardTitle>
            <CardDescription>Manage API keys for programmatic access</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-col gap-2">
              <Label>Label (optional)</Label>
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
                  placeholder="Prod integration"
                  value={newKeyLabel}
                  onChange={(e) => setNewKeyLabel(e.target.value)}
                />
                <Button onClick={handleCreateKey} disabled={createKey.isPending}>
                  {createKey.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Plus className="h-4 w-4 mr-2" />}
                  Create API Key
                </Button>
              </div>
              {newKeyValue && (
                <div className="p-3 rounded-md border border-border bg-muted/30 text-sm">
                  <p className="font-medium">Copy now:</p>
                  <code className="block break-all mt-1 text-emerald-500">{newKeyValue}</code>
                  <p className="text-xs text-muted-foreground mt-1">This key is shown only once.</p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>Existing keys</Label>
              <div className="space-y-2">
                {(apiKeys || []).map((k: any) => (
                  <div key={k.id} className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted/30">
                    <div>
                      <p className="font-medium">{k.label || "API Key"}</p>
                      <p className="text-xs text-muted-foreground">
                        Prefix: {k.prefix} • Created {new Date(k.createdAt).toLocaleString()}
                        {k.lastUsedAt ? ` • Last used ${new Date(k.lastUsedAt).toLocaleString()}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={async () => {
                          const raw = window.prompt("Enter full API key to validate");
                          if (!raw) return;
                          try {
                            const res = await validateKey.mutateAsync(raw.trim());
                            toast.success(res.valid ? "API key valid" : "Invalid key");
                          } catch (err: any) {
                            toast.error(err?.message || "Validation failed");
                          }
                        }}
                      >
                        Validate
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDeleteKey(k.id)} disabled={deleteKey.isPending}>
                        <Trash2 className="h-4 w-4 mr-1" />
                        Remove
                      </Button>
                    </div>
                  </div>
                ))}
                {(apiKeys || []).length === 0 && (
                  <div className="text-sm text-muted-foreground">No API keys yet.</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              Access Restrictions
            </CardTitle>
            <CardDescription>Advanced security controls</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div>
                <p className="font-medium">IP Allowlisting</p>
                <p className="text-sm text-muted-foreground">Restrict dashboard access to specific IPs</p>
              </div>
              <Badge variant="outline">Pro Plan</Badge>
            </div>
            <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
              <div>
                <p className="font-medium">Single Sign-On (SSO)</p>
                <p className="text-sm text-muted-foreground">Connect to your identity provider</p>
              </div>
              <Badge variant="outline">Enterprise</Badge>
            </div>
          </CardContent>
        </Card>
      </div>
    </SettingsPageLayout>
  );
}

