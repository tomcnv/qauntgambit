/**
 * Credential Manager Component
 * 
 * Simplified credential management focused on:
 * - Adding exchange API keys
 * - Verifying credentials
 * - Viewing balance
 * - Deleting credentials
 * 
 * Note: Risk/execution configs have moved to bot-exchange-configs level.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Plus,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Loader2,
  Eye,
  EyeOff,
  Key,
  Wallet,
  ExternalLink,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Badge } from "./ui/badge";
import { Switch } from "./ui/switch";
import { Dialog } from "./ui/dialog";
import { coreApiBaseUrl } from "../lib/quantgambit-url";

const AUTH_TOKEN_KEY = "deeptrader_token";

interface ExchangeCredential {
  id: string;
  exchange: string;
  label: string;
  status: "pending" | "verified" | "failed" | "disabled";
  last_verified_at: string | null;
  verification_error: string | null;
  permissions: string[];
  is_demo: boolean;
  created_at: string;
  exchange_balance?: number | null;
  balance_updated_at?: string | null;
  account_connected?: boolean;
  balance_currency?: string;
  connection_error?: string | null;
  balance_error?: string | null;
}

const EXCHANGES = [
  { id: "okx", name: "OKX", requiresPassphrase: true },
  { id: "binance", name: "Binance", requiresPassphrase: false },
  { id: "bybit", name: "Bybit", requiresPassphrase: false },
];

const STATUS_CONFIG = {
  verified: {
    label: "Verified",
    color: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    icon: CheckCircle2,
  },
  pending: {
    label: "Pending",
    color: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    icon: AlertCircle,
  },
  failed: {
    label: "Failed",
    color: "border-red-500/30 bg-red-500/10 text-red-300",
    icon: XCircle,
  },
  disabled: {
    label: "Disabled",
    color: "border-gray-500/30 bg-gray-500/10 text-gray-300",
    icon: XCircle,
  },
};

export default function CredentialManager() {
  const queryClient = useQueryClient();
  const [showAddDialog, setShowAddDialog] = useState(false);

  const { data: credentials, isLoading } = useQuery({
    queryKey: ["exchange-credentials"],
    queryFn: async () => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${coreApiBaseUrl()}/exchange-credentials`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to fetch credentials");
      const data = await res.json();
      return data.credentials as ExchangeCredential[];
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (credentialId: string) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to delete credential");
    },
    onSuccess: () => {
      toast.success("Credential deleted");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete credential");
    },
  });

  const verifyMutation = useMutation({
    mutationFn: async (credentialId: string) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/verify`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Verification failed");
    },
    onSuccess: () => {
      toast.success("Credential verified");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Verification failed");
    },
  });

  const refreshBalanceMutation = useMutation({
    mutationFn: async (credentialId: string) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/balance`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to refresh balance");
    },
    onSuccess: () => {
      toast.success("Balance refreshed");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to refresh balance");
    },
  });

  const handleDelete = (credentialId: string) => {
    if (!confirm("Delete this credential? This cannot be undone.")) return;
    deleteMutation.mutate(credentialId);
  };

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">Exchange Credentials</h3>
          <p className="text-sm text-muted-foreground">
            Manage your exchange API keys. Configuration is set per bot.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowAddDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Credential
        </Button>
      </div>

      {credentials?.length === 0 ? (
        <Card className="border-white/5 bg-black/30">
          <CardContent className="flex flex-col items-center justify-center py-8">
            <Key className="h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-sm text-muted-foreground mb-3">No exchange credentials configured</p>
            <Button size="sm" onClick={() => setShowAddDialog(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add Your First Credential
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {credentials?.map((cred) => (
            <CredentialCard
              key={cred.id}
              credential={cred}
              onVerify={() => verifyMutation.mutate(cred.id)}
              onRefreshBalance={() => refreshBalanceMutation.mutate(cred.id)}
              onDelete={() => handleDelete(cred.id)}
              isVerifying={verifyMutation.isPending}
              isRefreshing={refreshBalanceMutation.isPending}
            />
          ))}
        </div>
      )}

      <AddCredentialDialog
        open={showAddDialog}
        onClose={() => setShowAddDialog(false)}
      />
    </div>
  );
}

interface CredentialCardProps {
  credential: ExchangeCredential;
  onVerify: () => void;
  onRefreshBalance: () => void;
  onDelete: () => void;
  isVerifying?: boolean;
  isRefreshing?: boolean;
}

function CredentialCard({
  credential,
  onVerify,
  onRefreshBalance,
  onDelete,
  isVerifying,
  isRefreshing,
}: CredentialCardProps) {
  const status = STATUS_CONFIG[credential.status] || STATUS_CONFIG.pending;
  const StatusIcon = status.icon;

  return (
    <Card className="border-white/5 bg-black/30">
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold text-white capitalize">{credential.exchange}</span>
            {credential.is_demo && (
              <Badge variant="outline" className="text-[10px] border-amber-500/30 text-amber-300">
                Demo
              </Badge>
            )}
          </div>
          <Badge className={`text-xs ${status.color}`}>
            <StatusIcon className="h-3 w-3 mr-1" />
            {status.label}
          </Badge>
        </div>

        {credential.label && (
          <p className="text-sm text-muted-foreground mb-3">{credential.label}</p>
        )}

        {/* Balance */}
        {credential.exchange_balance !== null && credential.exchange_balance !== undefined && (
          <div className="rounded-lg bg-white/5 px-3 py-2 mb-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Account Balance</span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-semibold text-white">
                  ${credential.exchange_balance.toLocaleString()}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  onClick={onRefreshBalance}
                  disabled={isRefreshing}
                >
                  <RefreshCw className={`h-3 w-3 ${isRefreshing ? "animate-spin" : ""}`} />
                </Button>
              </div>
            </div>
            {credential.balance_updated_at && (
              <p className="text-[10px] text-muted-foreground mt-1">
                Updated {new Date(credential.balance_updated_at).toLocaleString()}
              </p>
            )}
          </div>
        )}

        {/* Error display */}
        {credential.verification_error && (
          <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-3 py-2 mb-3 text-xs text-red-300">
            <AlertCircle className="h-3 w-3 inline mr-1" />
            {credential.verification_error}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          {credential.status !== "verified" && (
            <Button
              variant="outline"
              size="sm"
              onClick={onVerify}
              disabled={isVerifying}
              className="flex-1"
            >
              {isVerifying ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <CheckCircle2 className="h-4 w-4 mr-2" />
              )}
              Verify
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={onDelete}
            className="text-red-400 hover:text-red-300"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>

        {/* Metadata */}
        <div className="mt-3 pt-3 border-t border-white/5 text-[10px] text-muted-foreground">
          Added {new Date(credential.created_at).toLocaleDateString()}
          {credential.last_verified_at && (
            <> • Verified {new Date(credential.last_verified_at).toLocaleDateString()}</>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

interface AddCredentialDialogProps {
  open: boolean;
  onClose: () => void;
}

function AddCredentialDialog({ open, onClose }: AddCredentialDialogProps) {
  const queryClient = useQueryClient();
  const [exchange, setExchange] = useState("");
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [isDemo, setIsDemo] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  const selectedExchange = EXCHANGES.find((e) => e.id === exchange);

  const createMutation = useMutation({
    mutationFn: async (data: {
      exchange: string;
      label: string;
      apiKey: string;
      secretKey: string;
      passphrase?: string;
      isDemo: boolean;
    }) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.message || "Failed to add credential");
      }
      return res.json();
    },
    onSuccess: () => {
      toast.success("Credential added successfully");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      resetForm();
      onClose();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to add credential");
    },
  });

  const resetForm = () => {
    setExchange("");
    setLabel("");
    setApiKey("");
    setSecretKey("");
    setPassphrase("");
    setIsDemo(false);
    setShowSecret(false);
  };

  const handleSubmit = () => {
    if (!exchange || !apiKey || !secretKey) {
      toast.error("Please fill in all required fields");
      return;
    }

    if (selectedExchange?.requiresPassphrase && !passphrase) {
      toast.error("Passphrase is required for this exchange");
      return;
    }

    createMutation.mutate({
      exchange,
      label: label || `${exchange.toUpperCase()} Account`,
      apiKey,
      secretKey,
      passphrase: selectedExchange?.requiresPassphrase ? passphrase : undefined,
      isDemo,
    });
  };

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="fixed inset-0 bg-black/60" onClick={onClose} />
        <div className="relative z-10 w-full max-w-md rounded-2xl border border-white/10 bg-[#0a0a0a] p-6 shadow-xl">
          <h2 className="text-xl font-semibold text-white mb-4">Add Exchange Credential</h2>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="exchange">Exchange *</Label>
              <select
                id="exchange"
                value={exchange}
                onChange={(e) => setExchange(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
              >
                <option value="">Select exchange</option>
                {EXCHANGES.map((ex) => (
                  <option key={ex.id} value={ex.id}>
                    {ex.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="label">Label (optional)</Label>
              <Input
                id="label"
                placeholder="e.g., Main Trading Account"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="apiKey">API Key *</Label>
              <Input
                id="apiKey"
                placeholder="Your API key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="secretKey">Secret Key *</Label>
              <div className="relative">
                <Input
                  id="secretKey"
                  type={showSecret ? "text" : "password"}
                  placeholder="Your secret key"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => setShowSecret(!showSecret)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                >
                  {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {selectedExchange?.requiresPassphrase && (
              <div className="space-y-2">
                <Label htmlFor="passphrase">Passphrase *</Label>
                <Input
                  id="passphrase"
                  type="password"
                  placeholder="Your passphrase"
                  value={passphrase}
                  onChange={(e) => setPassphrase(e.target.value)}
                />
              </div>
            )}

            <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-3">
              <div>
                <p className="text-sm font-medium text-white">Demo Trading</p>
                <p className="text-xs text-muted-foreground">Bybit and OKX only - not available for Binance</p>
              </div>
              <Switch checked={isDemo} onChange={(e) => setIsDemo(e.target.checked)} />
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={createMutation.isPending}>
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Plus className="h-4 w-4 mr-2" />
              )}
              Add Credential
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

