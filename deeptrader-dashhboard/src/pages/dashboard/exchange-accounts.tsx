/**
 * Exchange Accounts Management Page
 * 
 * CRUD for exchange accounts, credential management, and policy editing.
 */

import * as React from 'react';
import { DashBar } from "../../components/DashBar";
import {
  Plus,
  Trash2,
  Settings,
  RefreshCw,
  Shield,
  AlertTriangle,
  CheckCircle2,
  Key,
  Loader2,
  Pencil,
  Building2,
} from 'lucide-react';

// =============================================================================
// Exchange Logo Component
// =============================================================================

function ExchangeLogo({ venue, size = 'md' }: { venue: string; size?: 'sm' | 'md' | 'lg' }) {
  const sizeClasses = {
    sm: 'h-5 w-5 text-xs',
    md: 'h-8 w-8 text-sm',
    lg: 'h-10 w-10 text-base',
  };

  // Binance logo (yellow on dark)
  if (venue === 'binance') {
    return (
      <div className={`${sizeClasses[size]} rounded-lg bg-[#F0B90B] flex items-center justify-center`}>
        <svg viewBox="0 0 24 24" className="h-[60%] w-[60%] fill-black">
          <path d="M12 2L6.5 7.5L8.62 9.62L12 6.24L15.38 9.62L17.5 7.5L12 2ZM2 12L4.12 9.88L6.24 12L4.12 14.12L2 12ZM6.5 16.5L12 22L17.5 16.5L15.38 14.38L12 17.76L8.62 14.38L6.5 16.5ZM17.76 12L19.88 9.88L22 12L19.88 14.12L17.76 12ZM12 9.88L9.88 12L12 14.12L14.12 12L12 9.88Z"/>
        </svg>
      </div>
    );
  }

  // OKX logo (white on black)
  if (venue === 'okx') {
    return (
      <div className={`${sizeClasses[size]} rounded-lg bg-black flex items-center justify-center border border-white/20`}>
        <span className="font-bold text-white" style={{ fontSize: size === 'sm' ? '8px' : size === 'md' ? '10px' : '12px' }}>
          OKX
        </span>
      </div>
    );
  }

  // Bybit logo (orange gradient)
  if (venue === 'bybit') {
    return (
      <div className={`${sizeClasses[size]} rounded-lg bg-gradient-to-br from-[#F7A600] to-[#F05A28] flex items-center justify-center`}>
        <span className="font-bold text-white" style={{ fontSize: size === 'sm' ? '7px' : size === 'md' ? '9px' : '11px' }}>
          BYBIT
        </span>
      </div>
    );
  }

  // Default fallback
  return (
    <div className={`${sizeClasses[size]} rounded-lg bg-muted flex items-center justify-center`}>
      <span className="font-bold text-muted-foreground uppercase" style={{ fontSize: size === 'sm' ? '8px' : size === 'md' ? '10px' : '12px' }}>
        {venue.slice(0, 3)}
      </span>
    </div>
  );
}
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import toast from 'react-hot-toast';
import { cn } from '@/lib/utils';
import {
  useExchangeAccounts,
  useCreateExchangeAccount,
  useUpdateExchangeAccount,
  useDeleteExchangeAccount,
  useStoreCredentials,
  useRefreshBalance,
  useUpdatePaperCapital,
  useExchangePolicy,
  useUpdateExchangePolicy,
  useActivateKillSwitch,
  useDeactivateKillSwitch,
} from '@/lib/api/exchange-accounts-hooks';
import type { ExchangeAccount, ExchangePolicy, LinkedBot, CanDeleteResponse } from '@/lib/api/exchange-accounts';
import { checkCanDelete } from '@/lib/api/exchange-accounts';

const VENUES = [
  { value: 'okx', label: 'OKX' },
  { value: 'binance', label: 'Binance' },
  { value: 'bybit', label: 'Bybit' },
];

const ENVIRONMENTS = [
  { value: 'paper', label: 'Paper Trading', description: 'Orders simulated locally, never sent to exchange' },
  { value: 'live', label: 'Live Trading', description: 'Real orders sent to exchange' },
  { value: 'dev', label: 'Development', description: 'For development and testing' },
];

export default function ExchangeAccountsPage() {
  const [createOpen, setCreateOpen] = React.useState(false);
  const [selectedAccount, setSelectedAccount] = React.useState<ExchangeAccount | null>(null);
  const [credentialsOpen, setCredentialsOpen] = React.useState(false);
  const [policyOpen, setPolicyOpen] = React.useState(false);

  const { data: accounts = [], isLoading } = useExchangeAccounts();

  return (
    <>
      <DashBar />
      <div className="flex-1 overflow-auto">
        {/* Page Header */}
        <div className="sticky top-0 z-10 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b">
          <div className="px-6 py-4">
            <h1 className="text-2xl font-bold tracking-tight">Exchange Accounts</h1>
            <p className="text-sm text-muted-foreground">
              Manage your exchange connections and risk policies
            </p>
          </div>
        </div>

      <div className="p-6 space-y-6">
        {/* Header Actions */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Badge variant="outline" className="font-normal">
              {accounts.length} Account{accounts.length !== 1 ? 's' : ''}
            </Badge>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add Exchange Account
          </Button>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <CreateAccountDialog onClose={() => setCreateOpen(false)} />
          </Dialog>
        </div>

        {/* Accounts Grid */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : accounts.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Building2 className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">No Exchange Accounts</h3>
              <p className="text-muted-foreground text-center mb-4">
                Connect your first exchange account to start trading.
              </p>
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Add Exchange Account
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {accounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                onSelect={() => setSelectedAccount(account)}
                onCredentials={() => {
                  setSelectedAccount(account);
                  setCredentialsOpen(true);
                }}
                onPolicy={() => {
                  setSelectedAccount(account);
                  setPolicyOpen(true);
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Credentials Sheet */}
      <Sheet open={credentialsOpen} onOpenChange={setCredentialsOpen}>
        <SheetContent>
          {selectedAccount && (
            <CredentialsSheet
              account={selectedAccount}
              onClose={() => setCredentialsOpen(false)}
            />
          )}
        </SheetContent>
      </Sheet>

      {/* Policy Sheet */}
      <Sheet open={policyOpen} onOpenChange={setPolicyOpen}>
        <SheetContent className="sm:max-w-xl">
          {selectedAccount && (
            <PolicySheet
              account={selectedAccount}
              onClose={() => setPolicyOpen(false)}
            />
          )}
        </SheetContent>
      </Sheet>
      </div>
    </>
  );
}

// =============================================================================
// Account Card
// =============================================================================

function AccountCard({
  account,
  onSelect,
  onCredentials,
  onPolicy,
}: {
  account: ExchangeAccount;
  onSelect: () => void;
  onCredentials: () => void;
  onPolicy: () => void;
}) {
  const [deleteConfirmOpen, setDeleteConfirmOpen] = React.useState(false);
  const [deleteBlockedOpen, setDeleteBlockedOpen] = React.useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = React.useState('');
  const [linkedBots, setLinkedBots] = React.useState<LinkedBot[]>([]);
  const [checkingDelete, setCheckingDelete] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [editLabel, setEditLabel] = React.useState(account.label);
  const [editNotes, setEditNotes] = React.useState((account.metadata?.notes as string) || '');
  const [editIsDemo, setEditIsDemo] = React.useState(account.is_demo || false);
  const [editPaperCapital, setEditPaperCapital] = React.useState(
    String(account.metadata?.paperCapital || account.exchange_balance || 10000)
  );
  
  const deleteAccount = useDeleteExchangeAccount();
  const updateAccount = useUpdateExchangeAccount();
  const refreshBalance = useRefreshBalance();
  const updatePaperCapital = useUpdatePaperCapital();
  
  const isPaperAccount = account.environment === 'paper';

  const handleDeleteClick = async () => {
    setCheckingDelete(true);
    try {
      const result = await checkCanDelete(account.id);
      if (result.canDelete) {
        // No linked bots, show normal delete confirmation
        setDeleteConfirmOpen(true);
      } else {
        // Has linked bots, show blocked dialog
        setLinkedBots(result.linkedBots || []);
        setDeleteBlockedOpen(true);
      }
    } catch (err) {
      toast.error('Failed to check account status');
    } finally {
      setCheckingDelete(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteAccount.mutateAsync(account.id);
      toast.success('Account deleted');
      setDeleteConfirmOpen(false);
      setDeleteConfirmText('');
    } catch (err: unknown) {
      const error = err as Error & { response?: { data?: { error?: string; message?: string; linkedBots?: { name: string }[] } } };
      const apiMessage = error.response?.data?.message || error.response?.data?.error;
      toast.error(apiMessage || error.message || 'Failed to delete account');
    }
  };

  const handleEdit = async () => {
    try {
      // Update basic fields including demo mode
      await updateAccount.mutateAsync({
        id: account.id,
        params: {
          label: editLabel,
          isDemo: editIsDemo,
          metadata: { ...account.metadata, notes: editNotes },
        },
      });
      
      // For paper accounts, also update paper capital if changed
      if (isPaperAccount) {
        const newCapital = parseFloat(editPaperCapital);
        const currentCapital = account.metadata?.paperCapital || account.exchange_balance;
        if (newCapital > 0 && newCapital !== currentCapital) {
          await updatePaperCapital.mutateAsync({ id: account.id, paperCapital: newCapital });
        }
      }
      
      toast.success('Account updated');
      setEditOpen(false);
    } catch (err: unknown) {
      const error = err as Error;
      toast.error(error.message || 'Failed to update account');
    }
  };

  const handleRefresh = async () => {
    // Paper accounts don't need to refresh from exchange
    if (isPaperAccount) {
      toast.success('Paper trading balance is managed locally');
      return;
    }
    
    try {
      await refreshBalance.mutateAsync(account.id);
      toast.success('Balance refreshed from exchange');
    } catch (err: unknown) {
      const error = err as Error & { response?: { data?: { error?: string } } };
      const message = error.response?.data?.error || error.message || 'Failed to refresh balance';
      toast.error(message);
    }
  };

  const getStatusBadge = () => {
    if (account.kill_switch_enabled) {
      return (
        <Badge variant="warning" className="gap-1 border-red-500/50 bg-red-500/10 text-red-400">
          <AlertTriangle className="h-3 w-3" />
          Kill Switch
        </Badge>
      );
    }
    if (account.status === 'verified') {
      return (
        <Badge variant="success" className="gap-1">
          <CheckCircle2 className="h-3 w-3" />
          Verified
        </Badge>
      );
    }
    if (account.status === 'error') {
      return (
        <Badge variant="warning" className="gap-1 border-red-500/50 bg-red-500/10 text-red-400">
          Error
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="gap-1">
        Pending
      </Badge>
    );
  };

  // Combined trading mode badge - single badge showing both API type and trading mode
  const getTradingModeBadge = () => {
    const isDemo = account.is_demo;
    const env = account.environment;
    
    if (isDemo && env === 'live') {
      return { label: '🧪 Demo Trading', className: 'bg-amber-500/20 text-amber-400 border-amber-500/50' };
    }
    if (isDemo && env === 'paper') {
      return { label: '🧪 Demo Paper', className: 'bg-amber-500/20 text-amber-300 border-amber-500/30' };
    }
    if (!isDemo && env === 'live') {
      return { label: '🔥 Live Trading', className: 'bg-red-500/20 text-red-400 border-red-500/50' };
    }
    if (!isDemo && env === 'paper') {
      return { label: '📝 Paper Mode', className: 'bg-blue-500/20 text-blue-400 border-blue-500/50' };
    }
    // Dev mode
    return { label: '🔧 Dev Mode', className: 'bg-purple-500/20 text-purple-400 border-purple-500/50' };
  };

  const canDelete = deleteConfirmText === account.label;

  return (
    <>
      <Card className="relative overflow-hidden">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between">
            <div className="flex items-start gap-3">
              <ExchangeLogo venue={account.venue} size="md" />
              <div>
                <CardTitle className="text-lg">
                  {account.label}
                </CardTitle>
                <CardDescription className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className="uppercase font-medium">{account.venue}</span>
                  <Badge variant="outline" className={cn('text-xs', getTradingModeBadge().className)}>
                    {getTradingModeBadge().label}
                  </Badge>
                </CardDescription>
              </div>
            </div>
            {getStatusBadge()}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Balance */}
          {account.exchange_balance !== null && account.exchange_balance !== undefined && (
            <div className={cn('bg-muted/50 rounded-lg p-3', isPaperAccount && 'border border-blue-500/30')}>
              <div className="text-xs text-muted-foreground mb-1">
                {isPaperAccount ? 'Paper Capital' : 'Balance'}
              </div>
              <div className="text-xl font-bold">
                ${Number(account.exchange_balance).toLocaleString('en-US', { 
                  minimumFractionDigits: 2, 
                  maximumFractionDigits: 2 
                })}
                <span className="text-sm font-normal text-muted-foreground ml-1">
                  {account.balance_currency || 'USDT'}
                </span>
              </div>
              {!isPaperAccount && account.available_balance !== null && account.available_balance !== undefined && (
                <div className="text-xs text-muted-foreground mt-1">
                  Available: ${Number(account.available_balance).toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                  })}
                </div>
              )}
              {isPaperAccount && (
                <div className="text-xs text-blue-400 mt-1">
                  Simulated balance for paper trading
                </div>
              )}
            </div>
          )}

          {/* Notes */}
          {account.metadata?.notes && (
            <div className="text-sm text-muted-foreground italic">
              "{account.metadata.notes as string}"
            </div>
          )}

          {/* Bots info */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Bots</span>
            <span>
              {account.running_bot_count ?? 0} running / {account.bot_count ?? 0} total
            </span>
          </div>

          <Separator />

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={onCredentials} className="flex-1">
              <Key className="h-4 w-4 mr-1" />
              Credentials
            </Button>
            <Button variant="outline" size="sm" onClick={onPolicy} className="flex-1">
              <Shield className="h-4 w-4 mr-1" />
              Policy
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => {
                setEditLabel(account.label);
                setEditNotes((account.metadata?.notes as string) || '');
                setEditIsDemo(account.is_demo || false);
                setEditPaperCapital(String(account.metadata?.paperCapital || account.exchange_balance || 10000));
                setEditOpen(true);
              }}
              title="Edit account"
            >
              <Pencil className="h-4 w-4" />
            </Button>
            {!isPaperAccount && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleRefresh}
                disabled={refreshBalance.isPending}
                title="Refresh balance from exchange"
              >
                <RefreshCw className={cn('h-4 w-4', refreshBalance.isPending && 'animate-spin')} />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={handleDeleteClick}
              disabled={deleteAccount.isPending || checkingDelete}
              title="Delete account"
            >
              {checkingDelete ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4 text-destructive" />
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Edit Sheet */}
      <Sheet open={editOpen} onOpenChange={setEditOpen}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <ExchangeLogo venue={account.venue} size="sm" />
              Edit Account
            </SheetTitle>
            <SheetDescription>
              Update account details for {account.venue.toUpperCase()} ({account.environment})
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-6">
            <div className="space-y-2">
              <Label htmlFor="edit-label">Account Label</Label>
              <Input
                id="edit-label"
                value={editLabel}
                onChange={(e) => setEditLabel(e.target.value)}
                placeholder="e.g., Main Trading Account"
              />
              <p className="text-xs text-muted-foreground">
                A friendly name to identify this account
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-notes">Notes (optional)</Label>
              <Input
                id="edit-notes"
                value={editNotes}
                onChange={(e) => setEditNotes(e.target.value)}
                placeholder="e.g., Primary scalping account"
              />
              <p className="text-xs text-muted-foreground">
                Internal notes about this account
              </p>
            </div>

            {/* Paper Capital - only for paper accounts */}
            {isPaperAccount && (
              <div className="space-y-2">
                <Label htmlFor="edit-paper-capital">Paper Trading Capital (USDT)</Label>
                <Input
                  id="edit-paper-capital"
                  type="number"
                  value={editPaperCapital}
                  onChange={(e) => setEditPaperCapital(e.target.value)}
                  min="0"
                  step="100"
                />
                <p className="text-xs text-muted-foreground">
                  Simulated starting balance for paper trading
                </p>
              </div>
            )}

            {/* Demo toggle only for supported exchanges */}
            {DEMO_SUPPORTED_VENUES.includes(account.venue) ? (
              <>
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="space-y-0.5">
                    <Label htmlFor="edit-demo-toggle" className="text-sm font-medium">
                      Demo Trading
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      {account.venue === 'bybit' 
                        ? 'Use Bybit Demo Trading (api-demo.bybit.com)'
                        : 'Use OKX Demo Trading (simulated trading header)'
                      }
                    </p>
                  </div>
                  <Switch
                    id="edit-demo-toggle"
                    checked={editIsDemo}
                    onCheckedChange={setEditIsDemo}
                  />
                </div>
                {editIsDemo !== account.is_demo && (
                  <p className="text-xs text-amber-500">
                    Warning: Changing demo mode may require re-entering credentials
                  </p>
                )}
              </>
            ) : (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                <p className="text-xs text-amber-500">
                  <strong>Note:</strong> Demo trading is not available for {account.venue}. Use Paper Trading mode for risk-free testing.
                </p>
              </div>
            )}

            <Separator />

            <div className="space-y-2">
              <Label className="text-muted-foreground">Read-only</Label>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Exchange:</span>
                  <span className="ml-2 font-medium uppercase">{account.venue}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Environment:</span>
                  <span className="ml-2 font-medium capitalize">{account.environment}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Status:</span>
                  <span className="ml-2 font-medium capitalize">{account.status}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Created:</span>
                  <span className="ml-2">{new Date(account.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            </div>

            <div className="flex gap-2 pt-4">
              <Button variant="outline" onClick={() => setEditOpen(false)} className="flex-1">
                Cancel
              </Button>
              <Button 
                onClick={handleEdit} 
                disabled={
                  updateAccount.isPending || 
                  updatePaperCapital.isPending || 
                  !editLabel.trim() ||
                  (isPaperAccount && (!editPaperCapital || parseFloat(editPaperCapital) <= 0))
                }
                className="flex-1"
              >
                {(updateAccount.isPending || updatePaperCapital.isPending) && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                Save Changes
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>

      {/* Delete Confirmation Dialog */}
      <AlertDialog 
        open={deleteConfirmOpen} 
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteConfirmText('');
        }}
      >
        <AlertDialogContent className="border-red-500/50">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-red-500 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Delete Exchange Account?
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-4">
                <p>
                  You are about to delete{' '}
                  <strong className="text-foreground">{account.label}</strong>{' '}
                  ({account.venue.toUpperCase()} • {account.environment}).
                </p>
                
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 space-y-2">
                  <p className="font-semibold text-red-400 text-sm">This action will:</p>
                  <ul className="text-sm space-y-1 text-muted-foreground list-disc list-inside">
                    <li>Remove the exchange account connection</li>
                    <li>Delete stored API credentials</li>
                    <li>Remove all associated policy settings</li>
                    <li>Unlink any bots using this account</li>
                  </ul>
                </div>

                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
                  <p className="font-semibold text-amber-400 text-sm">What is preserved:</p>
                  <ul className="text-sm space-y-1 text-muted-foreground list-disc list-inside">
                    <li>Trade history and fills (for audit)</li>
                    <li>Bot configurations (but will need new account)</li>
                    <li>Positions on the exchange (must be closed manually)</li>
                  </ul>
                </div>

                <div className="space-y-2 pt-2">
                  <p className="text-sm text-muted-foreground">
                    To confirm, type{' '}
                    <span className="font-mono font-semibold text-foreground bg-muted px-1.5 py-0.5 rounded">
                      {account.label}
                    </span>{' '}
                    below:
                  </p>
                  <Input
                    value={deleteConfirmText}
                    onChange={(e) => setDeleteConfirmText(e.target.value)}
                    placeholder="Type account name to confirm"
                    className={cn(
                      'font-mono',
                      deleteConfirmText && !canDelete
                        ? 'border-red-500 focus-visible:ring-red-500'
                        : canDelete
                          ? 'border-green-500 focus-visible:ring-green-500'
                          : ''
                    )}
                    autoComplete="off"
                    autoFocus
                  />
                  {deleteConfirmText && !canDelete && (
                    <p className="text-xs text-red-400">Name doesn't match</p>
                  )}
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteConfirmText('')}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-red-600 hover:bg-red-700 disabled:bg-red-600/50"
              disabled={deleteAccount.isPending || !canDelete}
            >
              {deleteAccount.isPending && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Delete Permanently
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cannot Delete - Linked Bots Dialog */}
      <AlertDialog 
        open={deleteBlockedOpen} 
        onOpenChange={setDeleteBlockedOpen}
      >
        <AlertDialogContent className="border-amber-500/50">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-amber-500 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Cannot Delete Exchange Account
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-4">
                <p>
                  <strong className="text-foreground">{account.label}</strong> cannot be deleted because it has linked bots.
                </p>
                
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
                  <p className="font-semibold text-amber-400 text-sm">Linked Bots:</p>
                  <ul className="text-sm space-y-1 text-foreground">
                    {linkedBots.map((bot) => (
                      <li key={bot.id} className="flex items-center gap-2">
                        <span className="font-medium">{bot.name}</span>
                        <span className={cn(
                          'text-xs px-1.5 py-0.5 rounded',
                          bot.status === 'running' 
                            ? 'bg-green-500/20 text-green-400' 
                            : 'bg-muted text-muted-foreground'
                        )}>
                          {bot.status}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-lg border border-muted bg-muted/50 p-3 space-y-2">
                  <p className="font-semibold text-foreground text-sm">To delete this exchange account:</p>
                  <ol className="text-sm space-y-1 text-muted-foreground list-decimal list-inside">
                    <li>Go to the <strong className="text-foreground">Bot Management</strong> page</li>
                    <li>Delete or reassign the bots listed above</li>
                    <li>Return here to delete the exchange account</li>
                  </ol>
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Got it</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// =============================================================================
// Create Account Dialog
// =============================================================================

// Exchanges that support demo trading
const DEMO_SUPPORTED_VENUES = ['bybit', 'okx'];

function CreateAccountDialog({ onClose }: { onClose: () => void }) {
  const [venue, setVenue] = React.useState('okx');
  const [label, setLabel] = React.useState('');
  const [environment, setEnvironment] = React.useState('paper');
  const [isDemo, setIsDemo] = React.useState(false);
  const [paperCapital, setPaperCapital] = React.useState('10000');

  const createAccount = useCreateExchangeAccount();
  
  // Demo trading only available for Bybit and OKX
  const demoAvailable = DEMO_SUPPORTED_VENUES.includes(venue);

  const handleCreate = async () => {
    if (!label.trim()) {
      toast.error('Label is required');
      return;
    }
    
    if (environment === 'paper' && (!paperCapital || parseFloat(paperCapital) <= 0)) {
      toast.error('Paper capital must be greater than 0');
      return;
    }

    try {
      await createAccount.mutateAsync({
        venue,
        label: label.trim(),
        environment: environment as 'dev' | 'paper' | 'live',
        isDemo: demoAvailable ? isDemo : false, // Only pass isDemo for supported venues
        paperCapital: environment === 'paper' ? parseFloat(paperCapital) : undefined,
      });
      toast.success('Account created');
      onClose();
    } catch (err: unknown) {
      const error = err as Error;
      toast.error(error.message || 'Failed to create account');
    }
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Add Exchange Account</DialogTitle>
        <DialogDescription>
          Connect a new exchange account to DeepTrader.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4 py-4">
        <div className="space-y-2">
          <Label>Exchange</Label>
          <Select value={venue} onValueChange={setVenue}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VENUES.map((v) => (
                <SelectItem key={v.value} value={v.value}>
                  {v.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Label</Label>
          <Input
            placeholder="e.g., Main Account, Desk-1"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label>Trading Mode</Label>
          <Select value={environment} onValueChange={setEnvironment}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENVIRONMENTS.map((e) => (
                <SelectItem key={e.value} value={e.value}>
                  <div className="flex flex-col">
                    <span>{e.label}</span>
                    <span className="text-xs text-muted-foreground">{e.description}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Paper Capital - only shown for paper trading */}
        {environment === 'paper' && (
          <div className="space-y-2">
            <Label>Paper Trading Capital (USDT)</Label>
            <Input
              type="number"
              placeholder="10000"
              value={paperCapital}
              onChange={(e) => setPaperCapital(e.target.value)}
              min="0"
              step="100"
            />
            <p className="text-xs text-muted-foreground">
              Starting balance for paper trading simulation
            </p>
          </div>
        )}

        {/* Demo Trading Toggle - Only for Bybit and OKX */}
        {demoAvailable ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="demo-toggle" className="text-sm font-medium">
                  Demo Trading
                </Label>
                <p className="text-xs text-muted-foreground">
                  {venue === 'bybit' 
                    ? 'Use Bybit Demo Trading (api-demo.bybit.com) - simulated live trading with virtual funds'
                    : 'Use OKX Demo Trading - simulated live trading with virtual funds'
                  }
                </p>
              </div>
              <Switch
                id="demo-toggle"
                checked={isDemo}
                onCheckedChange={setIsDemo}
              />
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
            <p className="text-xs text-amber-500">
              <strong>Note:</strong> Binance does not support demo trading. Use <strong>Paper Trading</strong> mode for risk-free testing.
            </p>
          </div>
        )}

        {/* Clear explanation of what the current configuration means */}
        <div className="rounded-lg border bg-muted/50 p-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Configuration Summary</p>
          {environment === 'paper' ? (
            <div className="space-y-1">
              <p className="text-sm font-medium text-blue-400">📝 Paper Trading Mode</p>
              <ul className="text-xs text-muted-foreground space-y-0.5 list-disc list-inside">
                <li>Orders are <strong>simulated locally</strong> - never sent to exchange</li>
                <li>Market data from live {venue.toUpperCase()} endpoint</li>
                <li>Perfect for testing strategies risk-free</li>
              </ul>
            </div>
          ) : environment === 'live' ? (
            <div className="space-y-1">
              <p className="text-sm font-medium text-green-400">🔥 Live Trading Mode</p>
              <ul className="text-xs text-muted-foreground space-y-0.5 list-disc list-inside">
                <li><strong>Real orders</strong> will be sent to {isDemo && demoAvailable ? 'demo' : 'live'} {venue.toUpperCase()}</li>
                {isDemo && demoAvailable ? (
                  <li>Using demo funds (not real money)</li>
                ) : (
                  <li className="text-amber-400">⚠️ Using real funds - trade carefully!</li>
                )}
              </ul>
            </div>
          ) : (
            <div className="space-y-1">
              <p className="text-sm font-medium text-purple-400">🔧 Development Mode</p>
              <ul className="text-xs text-muted-foreground space-y-0.5 list-disc list-inside">
                <li>For development and testing purposes</li>
                <li>Market data from live endpoint</li>
              </ul>
            </div>
          )}
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleCreate} disabled={createAccount.isPending}>
          {createAccount.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Create Account
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

// =============================================================================
// Credentials Sheet
// =============================================================================

function CredentialsSheet({
  account,
  onClose,
}: {
  account: ExchangeAccount;
  onClose: () => void;
}) {
  const [apiKey, setApiKey] = React.useState('');
  const [secretKey, setSecretKey] = React.useState('');
  const [passphrase, setPassphrase] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const storeCredentials = useStoreCredentials();

  const handleSave = async () => {
    if (!apiKey || !secretKey) {
      toast.error('API key and secret key are required');
      return;
    }

    setError(null);
    
    try {
      await storeCredentials.mutateAsync({
        id: account.id,
        params: { apiKey, secretKey, passphrase: passphrase || undefined },
      });
      toast.success('Credentials verified and saved');
      onClose();
    } catch (err: unknown) {
      const error = err as Error & { response?: { data?: { code?: string; error?: string } } };
      const errorMessage = error.response?.data?.error || error.message || 'Failed to save credentials';
      const errorCode = error.response?.data?.code;
      
      if (errorCode === 'WITHDRAWAL_PERMISSION_DETECTED') {
        setError(errorMessage);
      } else {
        toast.error(errorMessage);
      }
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle>API Credentials</SheetTitle>
        <SheetDescription>
          Configure API credentials for {account.label} ({account.venue.toUpperCase()})
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-4 py-6">
        {/* Security Warning */}
        <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-4">
          <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="space-y-2">
              <p className="text-sm font-medium text-amber-500">Security Requirements</p>
              <ul className="text-xs text-amber-400/90 space-y-1 list-disc list-inside">
                <li><strong>DO NOT</strong> enable withdrawal permissions</li>
                <li>Only enable <strong>Read</strong> and <strong>Trade</strong> permissions</li>
                <li>Keys with withdrawal access will be <strong>rejected</strong></li>
                <li>Use IP restrictions when possible</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-500/10 p-4">
            <div className="flex gap-3">
              <AlertTriangle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-500">Security Violation</p>
                <p className="text-xs text-red-400/90 mt-1">{error}</p>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <Label>API Key</Label>
          <Input
            type="password"
            placeholder="Enter your API key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label>Secret Key</Label>
          <Input
            type="password"
            placeholder="Enter your secret key"
            value={secretKey}
            onChange={(e) => setSecretKey(e.target.value)}
          />
        </div>

        {account.venue === 'okx' && (
          <div className="space-y-2">
            <Label>Passphrase (OKX only)</Label>
            <Input
              type="password"
              placeholder="Enter your passphrase"
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
            />
          </div>
        )}

        {/* Permission Checklist */}
        <div className="rounded-lg border border-border/50 bg-muted/30 p-4">
          <p className="text-xs font-medium text-muted-foreground mb-2">Required Permissions</p>
          <div className="flex gap-4">
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              <span className="text-xs">Read</span>
            </div>
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              <span className="text-xs">Trade</span>
            </div>
            <div className="flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-red-500" />
              <span className="text-xs text-red-500 line-through">Withdraw</span>
            </div>
          </div>
        </div>

        <div className="pt-4">
          <Button
            onClick={handleSave}
            disabled={storeCredentials.isPending || !apiKey || !secretKey}
            className="w-full"
          >
            {storeCredentials.isPending && (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            )}
            Verify & Save
          </Button>
        </div>
      </div>
    </>
  );
}

// =============================================================================
// Policy Sheet
// =============================================================================

function PolicySheet({
  account,
  onClose,
}: {
  account: ExchangeAccount;
  onClose: () => void;
}) {
  const { data: policy, isLoading } = useExchangePolicy(account.id);
  const updatePolicy = useUpdateExchangePolicy();
  const activateKillSwitch = useActivateKillSwitch();
  const deactivateKillSwitch = useDeactivateKillSwitch();

  const [formData, setFormData] = React.useState<Partial<ExchangePolicy>>({});

  React.useEffect(() => {
    if (policy) {
      setFormData(policy);
    }
  }, [policy]);

  const handleSave = async () => {
    try {
      await updatePolicy.mutateAsync({
        accountId: account.id,
        params: {
          maxDailyLossPct: formData.max_daily_loss_pct,
          maxMarginUsedPct: formData.max_margin_used_pct,
          maxLeverage: formData.max_leverage,
          maxOpenPositions: formData.max_open_positions,
          circuitBreakerEnabled: formData.circuit_breaker_enabled,
          circuitBreakerLossPct: formData.circuit_breaker_loss_pct,
          liveTradingEnabled: formData.live_trading_enabled,
        },
      });
      toast.success('Policy updated');
    } catch (err: unknown) {
      const error = err as Error;
      toast.error(error.message || 'Failed to update policy');
    }
  };

  const handleKillSwitch = async () => {
    try {
      if (policy?.kill_switch_enabled) {
        await deactivateKillSwitch.mutateAsync(account.id);
        toast.success('Kill switch deactivated');
      } else {
        await activateKillSwitch.mutateAsync({ accountId: account.id, reason: 'Manual activation' });
        toast.success('Kill switch activated - all trading stopped');
      }
    } catch (err: unknown) {
      const error = err as Error;
      toast.error(error.message || 'Failed to toggle kill switch');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle>Risk Policy</SheetTitle>
        <SheetDescription>
          Configure risk limits for {account.label}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-6 py-6">
        {/* Kill Switch */}
        <Card className={cn(policy?.kill_switch_enabled && 'border-destructive')}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Kill Switch
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                Emergency stop all trading on this account
              </span>
              <Button
                variant="default"
                size="sm"
                onClick={handleKillSwitch}
                className={!policy?.kill_switch_enabled ? 'bg-red-600 hover:bg-red-700 border-red-600' : ''}
              >
                {policy?.kill_switch_enabled ? 'Deactivate' : 'Activate'}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Risk Limits */}
        <div className="space-y-4">
          <h4 className="font-medium">Risk Limits</h4>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Max Daily Loss %</Label>
              <Input
                type="number"
                value={formData.max_daily_loss_pct || ''}
                onChange={(e) =>
                  setFormData({ ...formData, max_daily_loss_pct: parseFloat(e.target.value) })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Max Margin Used %</Label>
              <Input
                type="number"
                value={formData.max_margin_used_pct || ''}
                onChange={(e) =>
                  setFormData({ ...formData, max_margin_used_pct: parseFloat(e.target.value) })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Max Leverage</Label>
              <Input
                type="number"
                value={formData.max_leverage || ''}
                onChange={(e) =>
                  setFormData({ ...formData, max_leverage: parseFloat(e.target.value) })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Max Open Positions</Label>
              <Input
                type="number"
                value={formData.max_open_positions || ''}
                onChange={(e) =>
                  setFormData({ ...formData, max_open_positions: parseInt(e.target.value) })
                }
              />
            </div>
          </div>
        </div>

        {/* Circuit Breaker */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="font-medium">Circuit Breaker</h4>
              <p className="text-sm text-muted-foreground">
                Auto-stop trading when daily loss exceeds threshold
              </p>
            </div>
            <Switch
              checked={formData.circuit_breaker_enabled || false}
              onCheckedChange={(checked) =>
                setFormData({ ...formData, circuit_breaker_enabled: checked })
              }
            />
          </div>

          {formData.circuit_breaker_enabled && (
            <div className="space-y-2">
              <Label>Trigger at % Loss</Label>
              <Input
                type="number"
                value={formData.circuit_breaker_loss_pct || ''}
                onChange={(e) =>
                  setFormData({ ...formData, circuit_breaker_loss_pct: parseFloat(e.target.value) })
                }
              />
            </div>
          )}
        </div>

        {/* Live Trading */}
        <div className="flex items-center justify-between">
          <div>
            <h4 className="font-medium">Live Trading</h4>
            <p className="text-sm text-muted-foreground">Enable live trading on this account</p>
          </div>
          <Switch
            checked={formData.live_trading_enabled || false}
            onCheckedChange={(checked) =>
              setFormData({ ...formData, live_trading_enabled: checked })
            }
          />
        </div>

        <Separator />

        <Button onClick={handleSave} disabled={updatePolicy.isPending} className="w-full">
          {updatePolicy.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Save Policy
        </Button>
      </div>
    </>
  );
}


