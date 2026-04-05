import { useEffect, useMemo, useState } from "react";
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
  ChevronDown,
  ChevronUp,
  Shield,
  Gauge,
  DollarSign,
  TrendingDown,
  Zap,
  Settings2,
  Info,
  Pencil,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Badge } from "./ui/badge";
import { Switch } from "./ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./ui/alert-dialog";
import { coreApiBaseUrl } from "../lib/quantgambit-url";

// Dynamically determine API URL based on current hostname
function getApiUrl(): string {
  return coreApiBaseUrl();
}

interface RiskConfig {
  positionSizePct: number;
  minPositionSizeUsd: number;
  maxPositionSizeUsd: number;
  maxPositions: number;
  maxPositionsPerStrategy: number;
  maxDailyLossPct: number;
  maxTotalExposurePct: number;
  maxExposurePerSymbolPct: number;
  maxLeverage: number;
  leverageMode: "isolated" | "cross";
  maxPositionsPerSymbol: number;
  maxDailyLossPerSymbolPct: number;
  maxDrawdownPct: number;
}

interface ExecutionConfig {
  defaultOrderType: string;
  stopLossPct: number;
  takeProfitPct: number;
  trailingStopEnabled: boolean;
  trailingStopPct: number;
  maxHoldTimeHours: number;
  minTradeIntervalSec: number;
  executionTimeoutSec: number;
  closePositionTimeoutSec: number;
  enableVolatilityFilter: boolean;
  volatilityShockCooldownSec: number;
  orderIntentMaxAgeSec: number;
}

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
  risk_config?: RiskConfig;
  execution_config?: ExecutionConfig;
  config_version?: number;
  // Balance fields
  exchange_balance?: number | null;
  balance_updated_at?: string | null;
  account_connected?: boolean;
  trading_capital?: number | null;
  balance_currency?: string;
  connection_error?: string | null;
  balance_error?: string | null;
}

interface TradeProfile {
  active_credential_id: string | null;
  active_exchange: string | null;
  trading_mode: "paper" | "live";
  token_lists: Record<string, string[]>;
  credential_status?: string | null;
  account_balance?: number;
  global_max_leverage?: number;
  global_leverage_mode?: string;
}

interface ExchangeLimits {
  exchange: string;
  max_leverage: number;
  default_leverage: number;
  min_position_usd: number;
  max_position_usd: number;
  supports_isolated_margin: boolean;
  supports_cross_margin: boolean;
  supports_trailing_stop: boolean;
}

type VerificationDetail = {
  text: string;
  tone: "success" | "warn" | "error" | "info";
  icon: "check" | "alert" | "info" | "spinner";
};

const verificationToneClasses: Record<VerificationDetail["tone"], string> = {
  success: "text-emerald-300",
  warn: "text-amber-300",
  error: "text-rose-300",
  info: "text-muted-foreground",
};

const DEFAULT_RISK_CONFIG: RiskConfig = {
  positionSizePct: 10.0,
  minPositionSizeUsd: 10,
  maxPositionSizeUsd: 0,
  maxPositions: 4,
  maxPositionsPerStrategy: 0,
  maxDailyLossPct: 5.0,
  maxTotalExposurePct: 40.0,
  maxExposurePerSymbolPct: 25.0,
  maxLeverage: 1,
  leverageMode: "isolated",
  maxPositionsPerSymbol: 1,
  maxDailyLossPerSymbolPct: 2.5,
  maxDrawdownPct: 10.0,
};

const DEFAULT_EXECUTION_CONFIG: ExecutionConfig = {
  defaultOrderType: "market",
  stopLossPct: 2.0,
  takeProfitPct: 5.0,
  trailingStopEnabled: false,
  trailingStopPct: 1.0,
  maxHoldTimeHours: 24,
  minTradeIntervalSec: 1.0,
  executionTimeoutSec: 5.0,
  closePositionTimeoutSec: 15.0,
  enableVolatilityFilter: true,
  volatilityShockCooldownSec: 30.0,
  orderIntentMaxAgeSec: 0,
};

const EXCHANGES = [
  { id: "okx", name: "OKX", requiresPassphrase: true },
  { id: "binance", name: "Binance", requiresPassphrase: false },
  { id: "bybit", name: "Bybit", requiresPassphrase: false },
];

const DEFAULT_TOKENS: Record<string, { symbol: string; base: string }[]> = {
  okx: [
    { symbol: "BTC-USDT-SWAP", base: "BTC" },
    { symbol: "ETH-USDT-SWAP", base: "ETH" },
    { symbol: "SOL-USDT-SWAP", base: "SOL" },
    { symbol: "DOGE-USDT-SWAP", base: "DOGE" },
    { symbol: "XRP-USDT-SWAP", base: "XRP" },
    { symbol: "LINK-USDT-SWAP", base: "LINK" },
    { symbol: "AVAX-USDT-SWAP", base: "AVAX" },
    { symbol: "MATIC-USDT-SWAP", base: "MATIC" },
  ],
  binance: [
    { symbol: "BTC-USDT-SWAP", base: "BTC" },
    { symbol: "ETH-USDT-SWAP", base: "ETH" },
    { symbol: "SOL-USDT-SWAP", base: "SOL" },
    { symbol: "DOGE-USDT-SWAP", base: "DOGE" },
    { symbol: "XRP-USDT-SWAP", base: "XRP" },
    { symbol: "LINK-USDT-SWAP", base: "LINK" },
  ],
  bybit: [
    { symbol: "BTC-USDT-SWAP", base: "BTC" },
    { symbol: "ETH-USDT-SWAP", base: "ETH" },
    { symbol: "SOL-USDT-SWAP", base: "SOL" },
    { symbol: "DOGE-USDT-SWAP", base: "DOGE" },
    { symbol: "XRP-USDT-SWAP", base: "XRP" },
  ],
};

const QUOTES = ["USDT", "USDC", "USD"];
const AUTH_TOKEN_KEY = "deeptrader_token";

const toPercentDisplay = (value: number | undefined) => {
  if (value === undefined || value === null) return value;
  return value > 1 ? value : value * 100;
};

const toDecimalValue = (value: number | undefined) => {
  if (value === undefined || value === null) return value;
  return value > 1 ? value / 100 : value;
};

const normalizeRiskConfigForDisplay = (config: RiskConfig) => ({
  ...config,
  positionSizePct: toPercentDisplay(config.positionSizePct) ?? config.positionSizePct,
  maxDailyLossPct: toPercentDisplay(config.maxDailyLossPct) ?? config.maxDailyLossPct,
  maxTotalExposurePct: toPercentDisplay(config.maxTotalExposurePct) ?? config.maxTotalExposurePct,
  maxExposurePerSymbolPct: toPercentDisplay(config.maxExposurePerSymbolPct) ?? config.maxExposurePerSymbolPct,
  maxDailyLossPerSymbolPct: toPercentDisplay(config.maxDailyLossPerSymbolPct) ?? config.maxDailyLossPerSymbolPct,
  maxDrawdownPct: toPercentDisplay(config.maxDrawdownPct) ?? config.maxDrawdownPct,
});

const normalizeExecutionConfigForDisplay = (config: ExecutionConfig) => ({
  ...config,
  stopLossPct: toPercentDisplay(config.stopLossPct) ?? config.stopLossPct,
  takeProfitPct: toPercentDisplay(config.takeProfitPct) ?? config.takeProfitPct,
  trailingStopPct: toPercentDisplay(config.trailingStopPct) ?? config.trailingStopPct,
});

const normalizeRiskConfigForApi = (config: RiskConfig) => ({
  ...config,
  positionSizePct: toDecimalValue(config.positionSizePct) ?? config.positionSizePct,
  maxDailyLossPct: toDecimalValue(config.maxDailyLossPct) ?? config.maxDailyLossPct,
  maxTotalExposurePct: toDecimalValue(config.maxTotalExposurePct) ?? config.maxTotalExposurePct,
  maxExposurePerSymbolPct: toDecimalValue(config.maxExposurePerSymbolPct) ?? config.maxExposurePerSymbolPct,
  maxDailyLossPerSymbolPct: toDecimalValue(config.maxDailyLossPerSymbolPct) ?? config.maxDailyLossPerSymbolPct,
  maxDrawdownPct: toDecimalValue(config.maxDrawdownPct) ?? config.maxDrawdownPct,
});

const normalizeExecutionConfigForApi = (config: ExecutionConfig) => ({
  ...config,
  stopLossPct: toDecimalValue(config.stopLossPct) ?? config.stopLossPct,
  takeProfitPct: toDecimalValue(config.takeProfitPct) ?? config.takeProfitPct,
  trailingStopPct: toDecimalValue(config.trailingStopPct) ?? config.trailingStopPct,
});

const normalizeInternalSymbol = (symbol: string) => {
  if (!symbol) return symbol;
  let normalized = symbol.trim().toUpperCase().replace("/", "-");
  if (normalized.endsWith("-SWAP")) return normalized;
  if (normalized.includes("-")) return normalized.endsWith("-SWAP") ? normalized : `${normalized}-SWAP`;
  for (const quote of QUOTES) {
    if (normalized.endsWith(quote)) {
      const base = normalized.slice(0, -quote.length);
      if (base) return `${base}-${quote}-SWAP`;
    }
  }
  return normalized.endsWith("-SWAP") ? normalized : `${normalized}-SWAP`;
};

const normalizeTokenList = (tokens: string[] | undefined): string[] => {
  if (!Array.isArray(tokens)) return [];
  return Array.from(new Set(tokens.map(normalizeInternalSymbol)));
};

async function fetchCredentials(): Promise<{ credentials: ExchangeCredential[] }> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch credentials");
  return res.json();
}

async function fetchProfile(): Promise<{ profile: TradeProfile }> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/profile`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch profile");
  return res.json();
}

async function fetchExchangeLimits(exchange: string): Promise<{ limits: ExchangeLimits }> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/limits/${exchange}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch limits");
  return res.json();
}

async function updateRiskConfig(credentialId: string, riskConfig: Partial<RiskConfig>) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/config/risk`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ riskConfig: normalizeRiskConfigForApi(riskConfig as RiskConfig) }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || "Failed to update risk config");
  }
  return res.json();
}

async function updateExecutionConfig(credentialId: string, executionConfig: Partial<ExecutionConfig>) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/config/execution`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ executionConfig: normalizeExecutionConfigForApi(executionConfig as ExecutionConfig) }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || "Failed to update execution config");
  }
  return res.json();
}

async function updateCredentialMetadataRequest(credentialId: string, payload: { label?: string; isDemo?: boolean }) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      label: payload.label,
      isDemo: payload.isDemo,
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.error || "Failed to update credential");
  }
  return res.json();
}

async function updateCredentialSecretsRequest(
  credentialId: string,
  secrets: { apiKey?: string; secretKey?: string; passphrase?: string }
) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/secrets`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(secrets),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.error || "Failed to update credential secrets");
  }
  return res.json();
}

async function updateAccountBalance(accountBalance: number) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/profile/balance`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ accountBalance }),
  });
  if (!res.ok) throw new Error("Failed to update account balance");
  return res.json();
}

async function refreshCredentialBalance(credentialId: string): Promise<{
  success: boolean;
  balance?: number;
  currency?: string;
  timestamp?: number;
  retryAfter?: number;
  accountConnected?: boolean;
  error?: string;
  errorCode?: string;
}> {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/refresh-balance`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err: Error & { retryAfter?: number; status?: number } = new Error(body.error || "Failed to refresh balance");
    err.retryAfter = body.retryAfter;
    err.status = res.status;
    throw err;
  }
  return body;
}

async function updateTradingCapital(credentialId: string, tradingCapital: number) {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const res = await fetch(`${getApiUrl()}/exchange-credentials/${credentialId}/trading-capital`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ tradingCapital }),
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || "Failed to update trading capital");
  }
  return res.json();
}

export default function ExchangeCredentials() {
  const queryClient = useQueryClient();
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedExchange, setSelectedExchange] = useState("okx");
  const [apiKey, setApiKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [label, setLabel] = useState("");
  const [isDemo, setIsDemo] = useState(false);
  const [showSecrets, setShowSecrets] = useState(false);
  
  // Config editing state
  const [expandedCredentialId, setExpandedCredentialId] = useState<string | null>(null);
  const [editingRiskConfig, setEditingRiskConfig] = useState<RiskConfig | null>(null);
  const [editingExecutionConfig, setEditingExecutionConfig] = useState<ExecutionConfig | null>(null);
  const [accountBalanceInput, setAccountBalanceInput] = useState<string>("");
  const [tradingCapitalInputs, setTradingCapitalInputs] = useState<Record<string, string>>({});
  const [refreshingCredentialId, setRefreshingCredentialId] = useState<string | null>(null);
  const [refreshCooldowns, setRefreshCooldowns] = useState<Record<string, number>>({});
  const [verifyingCredentialId, setVerifyingCredentialId] = useState<string | null>(null);
  const [showDemoCredentials, setShowDemoCredentials] = useState(true);
  const [editingCredential, setEditingCredential] = useState<ExchangeCredential | null>(null);
  const [editForm, setEditForm] = useState({
    label: "",
    isDemo: false,
    apiKey: "",
    secretKey: "",
    passphrase: "",
  });
  const [showEditSecrets, setShowEditSecrets] = useState(false);

  const { data: credentialsData, isLoading: loadingCredentials } = useQuery({
    queryKey: ["exchange-credentials"],
    queryFn: fetchCredentials,
  });

  const { data: profileData, isLoading: loadingProfile } = useQuery({
    queryKey: ["exchange-profile"],
    queryFn: fetchProfile,
  });
  
  const scheduleRefreshCooldown = (credentialId: string, retryAfter?: number) => {
    if (!retryAfter) return;
    setRefreshCooldowns((prev) => ({
      ...prev,
      [credentialId]: Date.now() + retryAfter * 1000,
    }));
  };

  useEffect(() => {
    if (!editingCredential) {
      setEditForm({
        label: "",
        isDemo: false,
        apiKey: "",
        secretKey: "",
        passphrase: "",
      });
      setShowEditSecrets(false);
      return;
    }
    setEditForm({
      label: editingCredential.label || "",
      isDemo: editingCredential.is_demo ?? false,
      apiKey: "",
      secretKey: "",
      passphrase: "",
    });
    setShowEditSecrets(false);
  }, [editingCredential]);
  
  // Fetch exchange limits when a credential is expanded
  const { data: limitsData } = useQuery({
    queryKey: ["exchange-limits", expandedCredentialId],
    queryFn: async () => {
      const cred = credentials.find(c => c.id === expandedCredentialId);
      if (!cred) return null;
      return fetchExchangeLimits(cred.exchange);
    },
    enabled: !!expandedCredentialId,
  });

  const addCredentialMutation = useMutation({
    mutationFn: async (data: {
      exchange: string;
      apiKey: string;
      secretKey: string;
      passphrase?: string;
      label?: string;
      isDemo: boolean;
    }) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.error || "Failed to add credentials");
      }
      return res.json();
    },
    onSuccess: () => {
      toast.success("Credentials added! Verification in progress...");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      resetForm();
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const deleteCredentialMutation = useMutation({
    mutationFn: async (id: string) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to delete credentials");
      return res.json();
    },
    onSuccess: () => {
      toast.success("Credentials deleted");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: () => {
      toast.error("Failed to delete credentials");
    },
  });

  const verifyCredentialMutation = useMutation({
    mutationFn: async (id: string) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/${id}/verify`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body?.error || "Failed to verify credentials");
      }
      return body;
    },
    onSuccess: (data) => {
      if (data.valid) {
        toast.success("Credentials verified successfully!");
        if (data.warning) {
          toast((t) => (
            <div className="text-sm">
              <p className="font-semibold text-amber-200">Verified with warning</p>
              <p className="text-amber-100/80">{data.warning}</p>
            </div>
          ));
        }
      } else {
        toast.error(`Verification failed: ${data.error}`);
      }
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Verification failed");
    },
  });

  const handleVerifyCredential = (credentialId: string) => {
    setVerifyingCredentialId(credentialId);
    verifyCredentialMutation.mutate(credentialId, {
      onSettled: () => setVerifyingCredentialId(null),
    });
  };

  const setActiveCredentialMutation = useMutation({
    mutationFn: async (credentialId: string) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/profile/active`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ credentialId }),
      });
      if (!res.ok) throw new Error("Failed to set active credential");
      return res.json();
    },
    onSuccess: () => {
      toast.success("Active exchange updated");
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const setTradingModeMutation = useMutation({
    mutationFn: async (mode: "paper" | "live") => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/profile/mode`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ mode }),
      });
      if (!res.ok) throw new Error("Failed to set trading mode");
      return res.json();
    },
    onSuccess: () => {
      toast.success("Trading mode updated");
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
    onError: () => {
      toast.error("Failed to update trading mode");
    },
  });

  const updateTokensMutation = useMutation({
    mutationFn: async ({ exchange, tokens }: { exchange: string; tokens: string[] }) => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${getApiUrl()}/exchange-credentials/profile/tokens/${exchange}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ tokens }),
      });
      if (!res.ok) throw new Error("Failed to update tokens");
      return res.json();
    },
    onSuccess: () => {
      toast.success("Token list updated");
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
    onError: () => {
      toast.error("Failed to update tokens");
    },
  });
  
  const updateRiskConfigMutation = useMutation({
    mutationFn: ({ credentialId, riskConfig }: { credentialId: string; riskConfig: Partial<RiskConfig> }) =>
      updateRiskConfig(credentialId, riskConfig),
    onSuccess: () => {
      toast.success("Risk configuration saved");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      setEditingRiskConfig(null);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
  
  const updateExecutionConfigMutation = useMutation({
    mutationFn: ({ credentialId, executionConfig }: { credentialId: string; executionConfig: Partial<ExecutionConfig> }) =>
      updateExecutionConfig(credentialId, executionConfig),
    onSuccess: () => {
      toast.success("Execution configuration saved");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      setEditingExecutionConfig(null);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const updateCredentialMetadataMutation = useMutation({
    mutationFn: ({ credentialId, label, isDemo }: { credentialId: string; label?: string; isDemo?: boolean }) =>
      updateCredentialMetadataRequest(credentialId, { label, isDemo }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
  });

  const updateCredentialSecretsMutation = useMutation({
    mutationFn: ({
      credentialId,
      apiKey,
      secretKey,
      passphrase,
    }: {
      credentialId: string;
      apiKey?: string;
      secretKey?: string;
      passphrase?: string;
    }) => updateCredentialSecretsRequest(credentialId, { apiKey, secretKey, passphrase }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
  });
  
  const updateAccountBalanceMutation = useMutation({
    mutationFn: (balance: number) => updateAccountBalance(balance),
    onSuccess: () => {
      toast.success("Account balance updated");
      queryClient.invalidateQueries({ queryKey: ["exchange-profile"] });
    },
    onError: () => {
      toast.error("Failed to update account balance");
    },
  });
  
  const refreshBalanceMutation = useMutation({
    mutationFn: (credentialId: string) => refreshCredentialBalance(credentialId),
    onMutate: (credentialId: string) => {
      setRefreshingCredentialId(credentialId);
    },
    onSuccess: (data, credentialId) => {
      if (data.success) {
        toast.success(
          `Balance: $${data.balance?.toFixed(2)} ${data.currency ?? ""}`.trim()
        );
      } else {
        toast.error(data.error || "Failed to fetch balance");
      }
      scheduleRefreshCooldown(credentialId, data.retryAfter);
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: (error: Error & { retryAfter?: number }) => {
      toast.error(error.message || "Failed to refresh balance");
      if (refreshingCredentialId) {
        scheduleRefreshCooldown(refreshingCredentialId, error.retryAfter);
      }
    },
    onSettled: () => {
      setRefreshingCredentialId(null);
    },
  });
  
  const updateTradingCapitalMutation = useMutation({
    mutationFn: ({ credentialId, tradingCapital }: { credentialId: string; tradingCapital: number }) =>
      updateTradingCapital(credentialId, tradingCapital),
    onSuccess: () => {
      toast.success("Trading capital updated");
      queryClient.invalidateQueries({ queryKey: ["exchange-credentials"] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const resetForm = () => {
    setShowAddForm(false);
    setSelectedExchange("okx");
    setApiKey("");
    setSecretKey("");
    setPassphrase("");
    setLabel("");
    setIsDemo(false);
    setShowSecrets(false);
  };

  const handleAddCredential = () => {
    if (!apiKey || !secretKey) {
      toast.error("API Key and Secret Key are required");
      return;
    }
    if (selectedExchange === "okx" && !passphrase) {
      toast.error("Passphrase is required for OKX");
      return;
    }

    addCredentialMutation.mutate({
      exchange: selectedExchange,
      apiKey,
      secretKey,
      passphrase: selectedExchange === "okx" ? passphrase : undefined,
      label: label || undefined,
      isDemo,
    });
  };

  const credentials = credentialsData?.credentials || [];
  const filteredCredentials = useMemo(
    () =>
      showDemoCredentials
        ? credentials
        : credentials.filter((cred) => !cred.is_demo),
    [credentials, showDemoCredentials]
  );
  const hasAnyCredentials = credentials.length > 0;
  const noFilteredResults = hasAnyCredentials && filteredCredentials.length === 0;
  const profile = profileData?.profile;
  const activeExchange = profile?.active_exchange || null;
  const hasVerifiedCredential = credentials.some((cred) => cred.status === "verified");
  const normalizedTokenLists = useMemo(() => {
    if (!profile?.token_lists) return {};
    return Object.entries(profile.token_lists).reduce((acc, [exchange, tokens]) => {
      acc[exchange] = normalizeTokenList(tokens as string[]);
      return acc;
    }, {} as Record<string, string[]>);
  }, [profile?.token_lists]);
  const activeTokens = activeExchange ? normalizedTokenLists[activeExchange] || [] : [];
  const hasVerifiedActiveCredential =
    Boolean(profile?.active_credential_id) && profile?.credential_status === "verified";
  const isSavingCredentialEdit =
    updateCredentialMetadataMutation.isPending || updateCredentialSecretsMutation.isPending;
  
  const handleEditCredentialSave = async () => {
    if (!editingCredential) return;
    try {
      await updateCredentialMetadataMutation.mutateAsync({
        credentialId: editingCredential.id,
        label: editForm.label || undefined,
        isDemo: editForm.isDemo,
      });
      const shouldUpdateSecrets =
        Boolean(editForm.apiKey) || Boolean(editForm.secretKey) || Boolean(editForm.passphrase);
      if (shouldUpdateSecrets) {
        await updateCredentialSecretsMutation.mutateAsync({
          credentialId: editingCredential.id,
          apiKey: editForm.apiKey || undefined,
          secretKey: editForm.secretKey || undefined,
          passphrase:
            editingCredential.exchange === "okx" ? editForm.passphrase || undefined : undefined,
        });
        toast.success("Credential secrets updated. Verification will re-run automatically.");
      } else {
        toast.success("Credential updated");
      }
      setEditingCredential(null);
    } catch (error) {
      toast.error((error as Error).message || "Failed to update credential");
    }
  };

  const formatShortTimestamp = (timestamp?: string | null) => {
    if (!timestamp) return null;
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  };

  const getVerificationDetails = (
    credential: ExchangeCredential,
    isVerifying: boolean
  ): VerificationDetail | null => {
    if (isVerifying) {
      return { text: "Verifying now…", tone: "info", icon: "spinner" };
    }

    if (credential.status === "verified") {
      const timestamp = formatShortTimestamp(credential.last_verified_at);
      return {
        text: timestamp ? `Verified ${timestamp}` : "Verified",
        tone: "success",
        icon: "check",
      };
    }

    if (credential.status === "failed") {
      return {
        text: credential.verification_error
          ? `Verification failed: ${credential.verification_error}`
          : "Verification failed",
        tone: "error",
        icon: "alert",
      };
    }

    if (credential.status === "pending") {
      if (credential.verification_error) {
        return {
          text: `Retry needed: ${credential.verification_error}`,
          tone: "warn",
          icon: "alert",
        };
      }
      return { text: "Awaiting verification", tone: "info", icon: "info" };
    }

    return null;
  };

  const getStatusBadge = (credential: ExchangeCredential, isVerifying: boolean) => {
    if (isVerifying) {
      return (
        <Badge variant="outline" className="gap-1 border-sky-500/40 text-sky-200">
          <Loader2 className="h-3 w-3 animate-spin" />
          Verifying
        </Badge>
      );
    }

    switch (credential.status) {
      case "verified":
        return (
          <Badge variant="success" className="gap-1">
            <CheckCircle2 className="h-3 w-3" /> Verified
          </Badge>
        );
      case "failed":
        return (
          <Badge variant="outline" className="gap-1 border-rose-500/60 text-rose-200">
            <XCircle className="h-3 w-3" /> Failed
          </Badge>
        );
      case "pending":
        return (
          <Badge variant="warning" className="gap-1">
            <AlertCircle className="h-3 w-3" /> Pending
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="capitalize text-muted-foreground">
            {credential.status}
          </Badge>
        );
    }
  };

  const renderVerificationIcon = (detail: VerificationDetail) => {
    switch (detail.icon) {
      case "spinner":
        return <Loader2 className="h-3 w-3 animate-spin" />;
      case "check":
        return <CheckCircle2 className="h-3 w-3" />;
      case "alert":
        return <AlertCircle className="h-3 w-3" />;
      default:
        return <Info className="h-3 w-3" />;
    }
  };

  if (loadingCredentials || loadingProfile) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Initialize account balance input from profile
  const accountBalance = profile?.account_balance || 10000;
  
  return (
    <div className="space-y-6">
      {/* Account Balance & Trading Mode */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Account Balance Card */}
        {hasVerifiedCredential ? (
          <Card className="border-white/5 bg-black/30">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.4em] text-muted-foreground">
                <DollarSign className="h-4 w-4" />
                Account Balance
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="relative flex-1">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">$</span>
                    <Input
                      type="number"
                      min={100}
                      step={100}
                      className="pl-7 text-lg font-semibold"
                      placeholder="10000"
                      defaultValue={accountBalance}
                      onChange={(e) => setAccountBalanceInput(e.target.value)}
                      onBlur={() => {
                        const val = parseFloat(accountBalanceInput);
                        if (val && val > 0 && val !== accountBalance) {
                          updateAccountBalanceMutation.mutate(val);
                        }
                      }}
                    />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  This balance is used for position sizing calculations. Enter your actual trading capital.
                </p>
                <div className="rounded-lg border border-white/5 bg-white/5 p-3">
                  <p className="text-xs font-medium text-muted-foreground mb-2">Quick Summary</p>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-muted-foreground">10% position:</span>
                      <span className="ml-1 font-medium text-white">${(accountBalance * 0.1).toFixed(0)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">5% daily loss:</span>
                      <span className="ml-1 font-medium text-rose-300">${(accountBalance * 0.05).toFixed(0)}</span>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="border-dashed border-white/10 bg-black/20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm uppercase tracking-[0.4em] text-muted-foreground">
                <DollarSign className="h-4 w-4" />
                Trading Capital
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Add and verify an exchange connection to unlock trading-capital controls. Once an exchange is connected,
                you’ll set the capital for that credential directly inside its configuration panel.
              </p>
            </CardContent>
          </Card>
        )}
        
        {/* Trading Mode Toggle */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Trading Mode
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold text-white">
                    {profile?.trading_mode === "live" ? "Live Trading" : "Paper Trading"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {profile?.trading_mode === "live"
                      ? "Real funds are at risk. Be careful!"
                      : "Practice with simulated trades. No real funds."}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-sm ${profile?.trading_mode === "paper" ? "text-primary" : "text-muted-foreground"}`}>
                    Paper
                  </span>
                  <Switch
                    checked={profile?.trading_mode === "live"}
                    disabled={!hasVerifiedActiveCredential || setTradingModeMutation.isPending}
                    onChange={(e) => setTradingModeMutation.mutate(e.target.checked ? "live" : "paper")}
                  />
                  <span className={`text-sm ${profile?.trading_mode === "live" ? "text-rose-400" : "text-muted-foreground"}`}>
                    Live
                  </span>
                </div>
              </div>
              {!hasVerifiedActiveCredential && (
                <p className="text-xs text-amber-300">
                  Add and verify an exchange connection to enable live trading.
                </p>
              )}
              {profile?.trading_mode === "live" && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3">
                  <p className="text-xs text-rose-300 font-medium">
                    Live mode is active. All trades will use real funds.
                  </p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Exchange Credentials */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Exchange Connections
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Keep live and sandbox credentials side-by-side.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <Switch
              id="toggle-demo"
              checked={showDemoCredentials}
              onChange={(event) => setShowDemoCredentials(event.target.checked)}
              label="Show demo credentials"
              className="text-xs text-muted-foreground"
            />
            <Button size="sm" onClick={() => setShowAddForm(true)} disabled={showAddForm}>
              <Plus className="mr-2 h-4 w-4" />
              Add Exchange
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Add Form */}
          {showAddForm && (
            <div className="rounded-2xl border border-primary/30 bg-primary/5 p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-white">Add New Exchange</h3>
                <Button variant="ghost" size="sm" onClick={resetForm}>
                  Cancel
                </Button>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Exchange</Label>
                  <select
                    value={selectedExchange}
                    onChange={(e) => setSelectedExchange(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
                  >
                    {EXCHANGES.map((ex) => (
                      <option key={ex.id} value={ex.id} className="bg-gray-900">
                        {ex.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <Label>Label (optional)</Label>
                  <Input
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                    placeholder="My Trading Account"
                  />
                </div>

                <div className="space-y-2">
                  <Label>API Key</Label>
                  <div className="relative">
                    <Input
                      type={showSecrets ? "text" : "password"}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="Enter API Key"
                    />
                    <button
                      type="button"
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-white"
                      onClick={() => setShowSecrets(!showSecrets)}
                    >
                      {showSecrets ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Secret Key</Label>
                  <Input
                    type={showSecrets ? "text" : "password"}
                    value={secretKey}
                    onChange={(e) => setSecretKey(e.target.value)}
                    placeholder="Enter Secret Key"
                  />
                </div>

                {selectedExchange === "okx" && (
                  <div className="space-y-2 md:col-span-2">
                    <Label>Passphrase (required for OKX)</Label>
                    <Input
                      type={showSecrets ? "text" : "password"}
                      value={passphrase}
                      onChange={(e) => setPassphrase(e.target.value)}
                      placeholder="Enter Passphrase"
                    />
                  </div>
                )}

                <div className="flex items-center gap-2 md:col-span-2">
                  <input
                    type="checkbox"
                    id="demo-toggle"
                    checked={isDemo}
                    onChange={(e) => setIsDemo(e.target.checked)}
                    className="h-4 w-4 rounded border-white/20 text-primary focus:ring-primary/60"
                  />
                  <Label htmlFor="demo-toggle" className="cursor-pointer">
                    Use Demo (paper trading with exchange)
                  </Label>
                </div>
              </div>

              <Button onClick={handleAddCredential} disabled={addCredentialMutation.isPending}>
                {addCredentialMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Key className="mr-2 h-4 w-4" />
                )}
                Save Credentials
              </Button>
            </div>
          )}

          {/* Existing Credentials */}
          {!hasAnyCredentials && !showAddForm ? (
            <div className="rounded-2xl border border-white/5 bg-white/5 p-8 text-center">
              <Key className="mx-auto h-12 w-12 text-muted-foreground" />
              <p className="mt-4 text-muted-foreground">No exchange connections yet</p>
              <p className="text-xs text-muted-foreground">Add your first exchange to start trading</p>
            </div>
          ) : noFilteredResults ? (
            <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-6 text-center text-sm text-amber-200">
              All exchanges are hidden by your filter. Enable "Show demo credentials" to see demo keys.
            </div>
          ) : (
            <div className="space-y-3">
              {filteredCredentials.map((cred) => {
                const isExpanded = expandedCredentialId === cred.id;
                const riskConfig = normalizeRiskConfigForDisplay(cred.risk_config || DEFAULT_RISK_CONFIG);
                const executionConfig = normalizeExecutionConfigForDisplay(cred.execution_config || DEFAULT_EXECUTION_CONFIG);
                const limits = limitsData?.limits;
                const exchangeBalance = cred.exchange_balance != null ? parseFloat(String(cred.exchange_balance)) : null;
                const tradingCapital = cred.trading_capital != null ? parseFloat(String(cred.trading_capital)) : null;
                const isConnected = cred.account_connected === true;
                const hasBalance = exchangeBalance != null && exchangeBalance > 0;
                const tradingCapitalInput = tradingCapitalInputs[cred.id] ?? (tradingCapital?.toString() || "");
                const isAtFullBalance = tradingCapital != null && exchangeBalance != null && tradingCapital >= exchangeBalance * 0.99;
                
                const balanceUpdatedAt = cred.balance_updated_at ? new Date(cred.balance_updated_at) : null;
                const lastUpdatedLabel = balanceUpdatedAt
                  ? `Updated ${balanceUpdatedAt.toLocaleString()}`
                  : "Balance has not been refreshed yet";
                const cooldownExpiresAt = refreshCooldowns[cred.id];
                const cooldownRemainingMs = cooldownExpiresAt ? cooldownExpiresAt - Date.now() : 0;
                const cooldownRemainingSeconds = cooldownRemainingMs > 0 ? Math.ceil(cooldownRemainingMs / 1000) : 0;
                const isRefreshing = refreshBalanceMutation.isPending && refreshingCredentialId === cred.id;
                const balanceError = cred.balance_error || cred.connection_error;
                const isVerifying = verifyingCredentialId === cred.id && verifyCredentialMutation.isPending;
                const statusBadge = getStatusBadge(cred, isVerifying);
                const verificationDetails = getVerificationDetails(cred, isVerifying);
                const verificationDetailClass = verificationDetails
                  ? verificationToneClasses[verificationDetails.tone]
                  : "";
                
                return (
                <div
                  key={cred.id}
                  className={`rounded-2xl border transition ${
                    cred.id === profile?.active_credential_id
                      ? "border-primary/60 bg-primary/10"
                      : "border-white/5 bg-white/5"
                  }`}
                >
                  {/* Credential Header */}
                  <div className="flex items-center justify-between p-4">
                    <div className="flex items-center gap-3">
                      <div className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold uppercase ${
                        isConnected ? "bg-emerald-500/20 text-emerald-400" : "bg-white/10"
                      }`}>
                        {cred.exchange.slice(0, 2)}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-white capitalize">{cred.exchange}</p>
                          {cred.label && (
                            <span className="text-xs text-muted-foreground">({cred.label})</span>
                          )}
                          {cred.is_demo && (
                            <Badge variant="outline" className="text-[10px] border-sky-500/40 text-sky-300">Demo</Badge>
                          )}
                        </div>
                    <div className="mt-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {statusBadge}
                        {isConnected ? (
                          <Badge variant="outline" className="text-[10px] border-emerald-500/50 text-emerald-400">Connected</Badge>
                        ) : cred.status === "verified" ? (
                          <Badge variant="outline" className="text-[10px] border-amber-500/50 text-amber-400">Disconnected</Badge>
                        ) : null}
                        {cred.config_version && (
                          <span className="text-xs text-muted-foreground">v{cred.config_version}</span>
                        )}
                      </div>
                      {verificationDetails && (
                        <p className={`mt-1 flex items-center gap-1 text-xs ${verificationDetailClass}`}>
                          {renderVerificationIcon(verificationDetails)}
                          {verificationDetails.text}
                        </p>
                      )}
                      {cred.exchange === "binance" && cred.is_demo && (
                        <p className="mt-1 text-[11px] text-amber-200">
                          Binance demo keys cannot return balances; set trading capital manually.
                        </p>
                      )}
                    </div>
                      </div>
                    </div>

                    {/* Balance Display */}
                    {cred.status === "verified" && (
                      <div className="flex items-center gap-4 mr-4">
                        <div className="text-right">
                          {hasBalance ? (
                            <>
                              <div className="flex items-center gap-1">
                                <span className="text-xs text-muted-foreground">Exchange Balance:</span>
                                <span className="text-sm font-semibold text-white">
                                  ${exchangeBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </span>
                              </div>
                              {tradingCapital != null && (
                                <div className="flex items-center gap-1">
                                  <span className="text-xs text-muted-foreground">Trading Capital:</span>
                                  <span className={`text-sm font-semibold ${isAtFullBalance ? "text-amber-400" : "text-emerald-400"}`}>
                                    ${tradingCapital.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                  </span>
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="flex items-center gap-2 text-amber-400">
                              <AlertCircle className="h-4 w-4" />
                              <span className="text-xs">No balance data</span>
                            </div>
                          )}
                          <p className="text-[11px] text-muted-foreground mt-1">{lastUpdatedLabel}</p>
                          {!cred.account_connected && (
                            <p className="text-[11px] text-amber-300">Connection lost</p>
                          )}
                          {cooldownRemainingSeconds > 0 && (
                            <p className="text-[11px] text-muted-foreground">
                              Next refresh in {cooldownRemainingSeconds}s
                            </p>
                          )}
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => refreshBalanceMutation.mutate(cred.id)}
                          disabled={isRefreshing}
                          title="Refresh balance from exchange"
                        >
                          {isRefreshing ? (
                            <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                          ) : (
                            <RefreshCw className="h-3 w-3 mr-1" />
                          )}
                          {isRefreshing ? "Refreshing..." : "Refresh"}
                        </Button>
                      </div>
                    )}

                    <div className="flex items-center gap-2">
                      {cred.status === "verified" && cred.id !== profile?.active_credential_id && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setActiveCredentialMutation.mutate(cred.id)}
                          disabled={setActiveCredentialMutation.isPending}
                        >
                          Set Active
                        </Button>
                      )}
                      {cred.id === profile?.active_credential_id && (
                        <Badge variant="default" className="uppercase">Active</Badge>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => setEditingCredential(cred)}
                        title="Edit credential settings"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (isExpanded) {
                            setExpandedCredentialId(null);
                            setEditingRiskConfig(null);
                            setEditingExecutionConfig(null);
                          } else {
                            setExpandedCredentialId(cred.id);
                            setEditingRiskConfig(normalizeRiskConfigForDisplay({ ...DEFAULT_RISK_CONFIG, ...riskConfig }));
                            setEditingExecutionConfig(normalizeExecutionConfigForDisplay({ ...DEFAULT_EXECUTION_CONFIG, ...executionConfig }));
                          }
                        }}
                        title="Configure Risk & Execution"
                        disabled={!hasBalance && cred.status === "verified"}
                      >
                        <Settings2 className="h-4 w-4 mr-1" />
                        Configure
                        {isExpanded ? <ChevronUp className="h-4 w-4 ml-1" /> : <ChevronDown className="h-4 w-4 ml-1" />}
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => handleVerifyCredential(cred.id)}
                        disabled={verifyCredentialMutation.isPending}
                      >
                        <RefreshCw className={`h-4 w-4 ${isVerifying ? "animate-spin" : ""}`} />
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent className="sm:max-w-md">
                          <AlertDialogHeader>
                            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/10">
                              <Trash2 className="h-6 w-6 text-rose-500" />
                            </div>
                            <AlertDialogTitle className="text-center">Delete Connection</AlertDialogTitle>
                            <AlertDialogDescription className="text-center">
                              Remove this <span className="font-semibold text-foreground">{cred.exchange}</span> exchange connection? Your API keys will be permanently deleted.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter className="sm:justify-center gap-2">
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction 
                              onClick={() => deleteCredentialMutation.mutate(cred.id)}
                              className="bg-rose-500 hover:bg-rose-600"
                            >
                              Delete
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>

                  {balanceError && (
                    <p className="px-4 pb-2 text-xs text-amber-300">
                      Last balance error: {balanceError}
                    </p>
                  )}
                  {cred.connection_error && !cred.verification_error && (
                    <p className="px-4 pb-2 text-xs text-amber-400">Connection issue: {cred.connection_error}</p>
                  )}
                  
                  {/* Trading Capital Section - Only show for verified credentials with balance */}
                  {cred.status === "verified" && hasBalance && (
                    <div className="px-4 pb-4 border-t border-white/5 pt-3">
                      <div className="flex items-center gap-4">
                        <div className="flex-1 max-w-xs">
                          <Label className="text-xs text-muted-foreground flex items-center gap-1">
                            <DollarSign className="h-3 w-3" />
                            Trading Capital (max ${exchangeBalance.toLocaleString()})
                          </Label>
                          <div className="flex items-center gap-2 mt-1">
                            <div className="relative flex-1">
                              <span className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">$</span>
                              <Input
                                type="number"
                                min={0}
                                max={exchangeBalance}
                                step={100}
                                className="pl-6"
                                placeholder={exchangeBalance.toString()}
                                value={tradingCapitalInput}
                                onChange={(e) => setTradingCapitalInputs(prev => ({
                                  ...prev,
                                  [cred.id]: e.target.value,
                                }))}
                                onBlur={() => {
                                  const val = parseFloat(tradingCapitalInput);
                                  if (!isNaN(val) && val > 0 && val !== tradingCapital) {
                                    updateTradingCapitalMutation.mutate({
                                      credentialId: cred.id,
                                      tradingCapital: val,
                                    });
                                  }
                                }}
                              />
                            </div>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setTradingCapitalInputs(prev => ({
                                  ...prev,
                                  [cred.id]: exchangeBalance.toString(),
                                }));
                                updateTradingCapitalMutation.mutate({
                                  credentialId: cred.id,
                                  tradingCapital: exchangeBalance,
                                });
                              }}
                              title="Set to full balance"
                            >
                              Max
                            </Button>
                          </div>
                        </div>
                        {isAtFullBalance && (
                          <div className="flex items-center gap-2 text-amber-400 text-xs">
                            <AlertCircle className="h-4 w-4" />
                            <span>No buffer - consider setting lower than balance</span>
                          </div>
                        )}
                        {tradingCapital != null && exchangeBalance != null && tradingCapital < exchangeBalance * 0.9 && (
                          <div className="flex items-center gap-2 text-emerald-400 text-xs">
                            <CheckCircle2 className="h-4 w-4" />
                            <span>{((1 - tradingCapital / exchangeBalance) * 100).toFixed(0)}% buffer reserved</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  
                  {/* Prompt to refresh balance if verified but no balance */}
                  {cred.status === "verified" && !hasBalance && (
                    <div className="px-4 pb-4 border-t border-white/5 pt-3">
                      {cred.exchange === "binance" && cred.is_demo ? (
                        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
                          Binance demo balances are not returned via API. Enter the trading capital you want to allocate and leave a buffer for unrealized PnL.
                        </div>
                      ) : (
                        <div className="flex items-center justify-between rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                          <div className="flex items-center gap-2 text-amber-300">
                            <AlertCircle className="h-4 w-4" />
                            <span className="text-sm">Click \"Refresh\" to fetch your exchange balance before configuring</span>
                          </div>
                          <Button
                            size="sm"
                            onClick={() => refreshBalanceMutation.mutate(cred.id)}
                            disabled={refreshBalanceMutation.isPending}
                          >
                            {refreshBalanceMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin mr-1" />
                            ) : (
                              <RefreshCw className="h-4 w-4 mr-1" />
                            )}
                            Fetch Balance
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                  
                  {/* Expanded Configuration Panel */}
                  {isExpanded && editingRiskConfig && editingExecutionConfig && (
                    <div className="border-t border-white/10 p-4 space-y-6">
                      {/* Risk Configuration */}
                      <div className="space-y-4">
                        <div className="flex items-center gap-2">
                          <Shield className="h-5 w-5 text-primary" />
                          <h4 className="font-semibold text-white">Risk Configuration</h4>
                          <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                            <Info className="h-3 w-3" />
                            {limits && <span>Max {limits.max_leverage}x leverage on {cred.exchange}</span>}
                          </div>
                        </div>
                        
                        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                          {/* Position Size */}
                          <div className="space-y-2">
                            <Label className="flex items-center gap-1">
                              <Gauge className="h-3 w-3" /> Position Size %
                            </Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={100}
                              step={0.1}
                              value={editingRiskConfig.positionSizePct}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                positionSizePct: parseFloat(e.target.value) || 0,
                              })}
                            />
                            <p className="text-xs text-muted-foreground">
                              ${((tradingCapital || exchangeBalance || 10000) * editingRiskConfig.positionSizePct / 100).toFixed(2)} per trade
                            </p>
                          </div>
                          
                          {/* Max Positions */}
                          <div className="space-y-2">
                            <Label>Max Concurrent Positions</Label>
                            <Input
                              type="number"
                              min={1}
                              max={20}
                              value={editingRiskConfig.maxPositions}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxPositions: parseInt(e.target.value) || 1,
                              })}
                            />
                          </div>
                          
                          {/* Max Leverage */}
                          <div className="space-y-2">
                            <Label className="flex items-center gap-1">
                              <Zap className="h-3 w-3" /> Max Leverage
                            </Label>
                            <Input
                              type="number"
                              min={1}
                              max={limits?.max_leverage || 125}
                              value={editingRiskConfig.maxLeverage}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxLeverage: Math.min(parseInt(e.target.value) || 1, limits?.max_leverage || 125),
                              })}
                            />
                            <p className="text-xs text-muted-foreground">
                              {editingRiskConfig.maxLeverage > 1 && (
                                <span className="text-amber-400">Higher leverage = higher risk</span>
                              )}
                            </p>
                          </div>
                          
                          {/* Leverage Mode */}
                          <div className="space-y-2">
                            <Label>Margin Mode</Label>
                            <select
                              value={editingRiskConfig.leverageMode}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                leverageMode: e.target.value as "isolated" | "cross",
                              })}
                              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
                            >
                              <option value="isolated" className="bg-gray-900">Isolated</option>
                              {limits?.supports_cross_margin && (
                                <option value="cross" className="bg-gray-900">Cross</option>
                              )}
                            </select>
                          </div>
                          
                          {/* Max Daily Loss */}
                          <div className="space-y-2">
                            <Label className="flex items-center gap-1">
                              <TrendingDown className="h-3 w-3" /> Max Daily Loss %
                            </Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={100}
                              step={0.1}
                              value={editingRiskConfig.maxDailyLossPct}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxDailyLossPct: parseFloat(e.target.value) || 0,
                              })}
                            />
                            <p className="text-xs text-muted-foreground">
                              ${((tradingCapital || exchangeBalance || 10000) * editingRiskConfig.maxDailyLossPct / 100).toFixed(2)} max loss
                            </p>
                          </div>
                          
                          {/* Max Total Exposure */}
                          <div className="space-y-2">
                            <Label>Max Total Exposure %</Label>
                            <Input
                              type="number"
                              min={1}
                              max={100}
                              step={1}
                              value={editingRiskConfig.maxTotalExposurePct}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxTotalExposurePct: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>

                          {/* Max Exposure Per Symbol */}
                          <div className="space-y-2">
                            <Label>Max Exposure Per Symbol %</Label>
                            <Input
                              type="number"
                              min={1}
                              max={100}
                              step={0.1}
                              value={editingRiskConfig.maxExposurePerSymbolPct}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxExposurePerSymbolPct: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>

                          {/* Min Position Size */}
                          <div className="space-y-2">
                            <Label>Min Position Size (USD)</Label>
                            <Input
                              type="number"
                              min={0}
                              step={1}
                              value={editingRiskConfig.minPositionSizeUsd}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                minPositionSizeUsd: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>

                          {/* Max Position Size */}
                          <div className="space-y-2">
                            <Label>Max Position Size (USD)</Label>
                            <Input
                              type="number"
                              min={0}
                              step={1}
                              value={editingRiskConfig.maxPositionSizeUsd}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxPositionSizeUsd: parseFloat(e.target.value) || 0,
                              })}
                            />
                            <p className="text-xs text-muted-foreground">0 = no cap</p>
                          </div>
                          
                          {/* Max Positions Per Symbol */}
                          <div className="space-y-2">
                            <Label>Max Positions Per Symbol</Label>
                            <Input
                              type="number"
                              min={1}
                              max={5}
                              value={editingRiskConfig.maxPositionsPerSymbol}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxPositionsPerSymbol: parseInt(e.target.value) || 1,
                              })}
                            />
                          </div>
                          
                          {/* Max Daily Loss Per Symbol */}
                          <div className="space-y-2">
                            <Label>Max Daily Loss Per Symbol %</Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={100}
                              step={0.1}
                              value={editingRiskConfig.maxDailyLossPerSymbolPct}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxDailyLossPerSymbolPct: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>

                          {/* Max Positions Per Strategy */}
                          <div className="space-y-2">
                            <Label>Max Positions Per Strategy</Label>
                            <Input
                              type="number"
                              min={0}
                              max={20}
                              value={editingRiskConfig.maxPositionsPerStrategy}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxPositionsPerStrategy: parseInt(e.target.value) || 0,
                              })}
                            />
                            <p className="text-xs text-muted-foreground">0 = no limit</p>
                          </div>

                          {/* Max Drawdown */}
                          <div className="space-y-2">
                            <Label>Max Drawdown %</Label>
                            <Input
                              type="number"
                              min={0}
                              max={100}
                              step={0.1}
                              value={editingRiskConfig.maxDrawdownPct}
                              onChange={(e) => setEditingRiskConfig({
                                ...editingRiskConfig,
                                maxDrawdownPct: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>
                        </div>
                        
                        <Button
                          onClick={() => updateRiskConfigMutation.mutate({ credentialId: cred.id, riskConfig: editingRiskConfig })}
                          disabled={updateRiskConfigMutation.isPending}
                        >
                          {updateRiskConfigMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Shield className="mr-2 h-4 w-4" />
                          )}
                          Save Risk Config
                        </Button>
                      </div>
                      
                      {/* Execution Configuration */}
                      <div className="space-y-4 border-t border-white/10 pt-4">
                        <div className="flex items-center gap-2">
                          <Zap className="h-5 w-5 text-emerald-400" />
                          <h4 className="font-semibold text-white">Execution & Exit Rules</h4>
                        </div>
                        
                        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                          {/* Stop Loss */}
                          <div className="space-y-2">
                            <Label className="text-rose-300">Default Stop Loss %</Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={50}
                              step={0.1}
                              value={editingExecutionConfig.stopLossPct}
                              onChange={(e) => setEditingExecutionConfig({
                                ...editingExecutionConfig,
                                stopLossPct: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>
                          
                          {/* Take Profit */}
                          <div className="space-y-2">
                            <Label className="text-emerald-300">Default Take Profit %</Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={100}
                              step={0.1}
                              value={editingExecutionConfig.takeProfitPct}
                              onChange={(e) => setEditingExecutionConfig({
                                ...editingExecutionConfig,
                                takeProfitPct: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>
                          
                          {/* Trailing Stop */}
                          <div className="space-y-2">
                            <Label>Trailing Stop</Label>
                            <div className="flex items-center gap-2">
                              <Switch
                                checked={editingExecutionConfig.trailingStopEnabled}
                                onChange={(e) => setEditingExecutionConfig({
                                  ...editingExecutionConfig,
                                  trailingStopEnabled: e.target.checked,
                                })}
                              />
                              {editingExecutionConfig.trailingStopEnabled && (
                                <Input
                                  type="number"
                                  min={0.1}
                                  max={10}
                                  step={0.1}
                                  value={editingExecutionConfig.trailingStopPct}
                                  onChange={(e) => setEditingExecutionConfig({
                                    ...editingExecutionConfig,
                                    trailingStopPct: parseFloat(e.target.value) || 0,
                                  })}
                                  className="w-20"
                                />
                              )}
                            </div>
                          </div>
                          
                          {/* Max Hold Time */}
                          <div className="space-y-2">
                            <Label>Max Hold Time (hours)</Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={168}
                              step={0.5}
                              value={editingExecutionConfig.maxHoldTimeHours}
                              onChange={(e) => setEditingExecutionConfig({
                                ...editingExecutionConfig,
                                maxHoldTimeHours: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>
                          
                          {/* Volatility Filter */}
                          <div className="space-y-2">
                            <Label>Volatility Filter</Label>
                            <div className="flex items-center gap-2">
                              <Switch
                                checked={editingExecutionConfig.enableVolatilityFilter}
                                onChange={(e) => setEditingExecutionConfig({
                                  ...editingExecutionConfig,
                                  enableVolatilityFilter: e.target.checked,
                                })}
                              />
                              <span className="text-xs text-muted-foreground">
                                {editingExecutionConfig.enableVolatilityFilter ? "Enabled" : "Disabled"}
                              </span>
                            </div>
                          </div>
                          
                          {/* Min Trade Interval */}
                          <div className="space-y-2">
                            <Label>Min Trade Interval (sec)</Label>
                            <Input
                              type="number"
                              min={0.1}
                              max={60}
                              step={0.1}
                              value={editingExecutionConfig.minTradeIntervalSec}
                              onChange={(e) => setEditingExecutionConfig({
                                ...editingExecutionConfig,
                                minTradeIntervalSec: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>
                          
                          {/* Execution Timeout */}
                          <div className="space-y-2">
                            <Label>Execution Timeout (sec)</Label>
                            <Input
                              type="number"
                              min={1}
                              max={30}
                              step={1}
                              value={editingExecutionConfig.executionTimeoutSec}
                              onChange={(e) => setEditingExecutionConfig({
                                ...editingExecutionConfig,
                                executionTimeoutSec: parseFloat(e.target.value) || 0,
                              })}
                            />
                          </div>

                          {/* Order Intent Max Age */}
                          <div className="space-y-2">
                            <Label>Order Intent Max Age (sec)</Label>
                            <Input
                              type="number"
                              min={0}
                              max={3600}
                              step={1}
                              value={editingExecutionConfig.orderIntentMaxAgeSec}
                              onChange={(e) => setEditingExecutionConfig({
                                ...editingExecutionConfig,
                                orderIntentMaxAgeSec: parseFloat(e.target.value) || 0,
                              })}
                            />
                            <p className="text-xs text-muted-foreground">0 = disable intent age guard</p>
                          </div>
                          
                          {/* Volatility Cooldown */}
                          {editingExecutionConfig.enableVolatilityFilter && (
                            <div className="space-y-2">
                              <Label>Volatility Cooldown (sec)</Label>
                              <Input
                                type="number"
                                min={1}
                                max={300}
                                step={1}
                                value={editingExecutionConfig.volatilityShockCooldownSec}
                                onChange={(e) => setEditingExecutionConfig({
                                  ...editingExecutionConfig,
                                  volatilityShockCooldownSec: parseFloat(e.target.value) || 0,
                                })}
                              />
                            </div>
                          )}
                        </div>
                        
                        <Button
                          onClick={() => updateExecutionConfigMutation.mutate({ credentialId: cred.id, executionConfig: editingExecutionConfig })}
                          disabled={updateExecutionConfigMutation.isPending}
                        >
                          {updateExecutionConfigMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Zap className="mr-2 h-4 w-4" />
                          )}
                          Save Execution Config
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Token Selection for Active Exchange */}
      {activeExchange && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Trading Pairs for {activeExchange.toUpperCase()}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
              {(DEFAULT_TOKENS[activeExchange] || []).map((token) => {
                const currentTokens = activeTokens;
                const isSelected = currentTokens.includes(token.symbol);

                return (
                  <label
                    key={token.symbol}
                    className="flex items-center gap-2 rounded-lg border border-white/5 bg-white/5 p-3 cursor-pointer hover:border-white/15 transition"
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => {
                        const updated = e.target.checked
                          ? [...currentTokens, token.symbol]
                          : currentTokens.filter((t) => t !== token.symbol);
                        updateTokensMutation.mutate({
                          exchange: activeExchange,
                          tokens: normalizeTokenList(updated),
                        });
                      }}
                      className="h-4 w-4 rounded border-white/20 text-primary focus:ring-primary/60"
                    />
                    <span className="text-sm text-foreground">{token.base}/USDT</span>
                  </label>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

  <Dialog
    open={Boolean(editingCredential)}
    onOpenChange={(open) => {
      if (!open && !isSavingCredentialEdit) {
        setEditingCredential(null);
      }
    }}
  >
    <DialogContent className="max-w-lg">
      <DialogHeader>
        <DialogTitle>Edit Exchange Connection</DialogTitle>
        <DialogDescription>
          Update the label or toggle demo mode. Leave secret fields blank to keep the existing keys.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label>Label</Label>
          <Input
            value={editForm.label}
            onChange={(e) => setEditForm((prev) => ({ ...prev, label: e.target.value }))}
            placeholder="My Binance Demo"
          />
        </div>
        <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
          <div>
            <p className="text-sm font-medium text-white">Use Demo</p>
            <p className="text-xs text-muted-foreground">
              Demo keys only work when demo mode is enabled. Live keys must disable it.
            </p>
          </div>
          <Switch
            checked={editForm.isDemo}
            onChange={(event) =>
              setEditForm((prev) => ({ ...prev, isDemo: event.target.checked }))
            }
          />
        </div>

        <div className="rounded-lg border border-white/10 p-3 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-white">API Keys</p>
            <Button variant="ghost" size="sm" onClick={() => setShowEditSecrets((prev) => !prev)}>
              {showEditSecrets ? (
                <>
                  <EyeOff className="h-3 w-3 mr-1" /> Hide
                </>
              ) : (
                <>
                  <Eye className="h-3 w-3 mr-1" /> Show
                </>
              )}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Leave every field blank to keep the existing secrets unchanged.
          </p>
          <div className="space-y-2">
            <Label>API Key</Label>
            <Input
              type={showEditSecrets ? "text" : "password"}
              value={editForm.apiKey}
              onChange={(e) => setEditForm((prev) => ({ ...prev, apiKey: e.target.value }))}
            />
          </div>
          <div className="space-y-2">
            <Label>Secret Key</Label>
            <Input
              type={showEditSecrets ? "text" : "password"}
              value={editForm.secretKey}
              onChange={(e) => setEditForm((prev) => ({ ...prev, secretKey: e.target.value }))}
            />
          </div>
          {editingCredential?.exchange === "okx" && (
            <div className="space-y-2">
              <Label>Passphrase</Label>
              <Input
                type={showEditSecrets ? "text" : "password"}
                value={editForm.passphrase}
                onChange={(e) => setEditForm((prev) => ({ ...prev, passphrase: e.target.value }))}
              />
            </div>
          )}
          {editingCredential?.exchange === "binance" && editForm.isDemo && (
            <p className="text-xs text-amber-200">
              Binance demo balances are not returned via API. Enter trading capital manually after verification.
            </p>
          )}
        </div>
      </div>
      <DialogFooter className="mt-6 flex justify-between">
        <Button
          variant="ghost"
          onClick={() => !isSavingCredentialEdit && setEditingCredential(null)}
          disabled={isSavingCredentialEdit}
        >
          Cancel
        </Button>
        <Button onClick={handleEditCredentialSave} disabled={isSavingCredentialEdit}>
          {isSavingCredentialEdit ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
          Save Changes
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
    </div>
  );
}
