/**
 * Exchange Form Component
 * Exchange account selection and environment
 */

import { Lock } from "lucide-react";
import { Label } from "../../../components/ui/label";
import { Badge } from "../../../components/ui/badge";
import { cn } from "../../../lib/utils";
import { ENVIRONMENTS } from "../types";
import type { BotEnvironment, ExchangeAccountOption } from "../types";

interface ExchangeFormProps {
  credentialId: string;
  setCredentialId: (id: string) => void;
  environment: BotEnvironment;
  setEnvironment: (env: BotEnvironment) => void;
  verifiedAccounts: ExchangeAccountOption[];
  isLoading?: boolean;
  /** When true, environment cannot be changed (existing bot config) */
  isEditing?: boolean;
}

export function ExchangeForm({
  credentialId,
  setCredentialId,
  environment,
  setEnvironment,
  verifiedAccounts,
  isLoading,
  isEditing = false,
}: ExchangeFormProps) {
  const currentEnvConfig = ENVIRONMENTS.find((e) => e.value === environment);
  
  return (
    <div className="space-y-4">
      {/* Exchange Account */}
      <div className="space-y-2">
        <Label>Exchange Account</Label>
        {verifiedAccounts.length === 0 ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
            <p className="font-medium text-amber-400">No verified exchange accounts</p>
            <p className="text-muted-foreground mt-1">
              Add and verify an exchange account in Settings → Exchange Accounts
            </p>
          </div>
        ) : (
          <div className="grid gap-2">
            {verifiedAccounts.map((account) => (
              <button
                key={account.id}
                type="button"
                onClick={() => setCredentialId(account.id)}
                className={cn(
                  "rounded-lg border p-3 text-left transition-all flex items-center justify-between",
                  credentialId === account.id
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                )}
              >
                <div>
                  <span className="font-medium uppercase">{account.venue}</span>
                  <span className="text-muted-foreground ml-2">• {account.label}</span>
                  <Badge variant="outline" className="ml-2 text-xs capitalize">
                    {account.environment}
                  </Badge>
                </div>
                {account.available_balance !== undefined && (
                  <span className="text-sm font-mono">
                    ${Number(account.available_balance).toLocaleString("en-US", {
                      maximumFractionDigits: 2,
                    })}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Environment */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label>Environment</Label>
          {isEditing && (
            <Badge variant="outline" className="text-xs gap-1">
              <Lock className="h-3 w-3" />
              Locked
            </Badge>
          )}
        </div>
        
        {isEditing ? (
          // Read-only display for existing bot configs
          <div className="space-y-2">
            <div className={cn(
              "rounded-lg border p-3 text-center",
              "border-primary bg-primary/10"
            )}>
              <span className="font-medium text-sm">{currentEnvConfig?.label || environment}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Environment is locked after creation to prevent mixing live and paper trades on the same bot.
            </p>
          </div>
        ) : (
          // Editable for new bot configs
          <div className="grid grid-cols-3 gap-2">
            {ENVIRONMENTS.filter((e) => e.value !== "all").map((env) => (
              <button
                key={env.value}
                type="button"
                onClick={() => setEnvironment(env.value as BotEnvironment)}
                className={cn(
                  "rounded-lg border p-3 text-center transition-all",
                  environment === env.value
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                )}
              >
                <span className="font-medium text-sm">{env.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}





