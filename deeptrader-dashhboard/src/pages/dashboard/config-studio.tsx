import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Loader2, RefreshCcw } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Separator } from "../../components/ui/separator";
import { useBotProfiles, useBotProfileDetail, useActiveBot } from "../../lib/api/hooks";
import { activateBotVersion, setActiveBot } from "../../lib/api/client";
import { BotProfile, BotProfileVersion } from "../../lib/api/types";
import { cn } from "../../lib/utils";

export default function ConfigStudioPage() {
  const queryClient = useQueryClient();
  const { data: botList, isLoading: botsLoading, isFetching: botsFetching } = useBotProfiles();
  const { data: activeBotData } = useActiveBot();
  const systemActiveBotId = activeBotData?.bot?.id ?? null;
  const bots = botList?.bots ?? [];
  const [selectedBotId, setSelectedBotId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedBotId && bots.length > 0) {
      setSelectedBotId(bots[0].id);
    }
  }, [bots, selectedBotId]);

  const activeBotId = selectedBotId ?? bots[0]?.id;
  const { data: botDetail, isFetching: detailFetching } = useBotProfileDetail(activeBotId);
  const versions = botDetail?.versions ?? [];

  const activationMutation = useMutation({
    mutationFn: ({ botId, versionId }: { botId: string; versionId: string }) => activateBotVersion(botId, versionId),
    onSuccess: (_, variables) => {
      toast.success("Version activated");
      queryClient.invalidateQueries({ queryKey: ["bot-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["bot-profile", variables.botId] });
      queryClient.invalidateQueries({ queryKey: ["active-bot"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Activation failed");
    },
  });

  const setActiveBotMutation = useMutation({
    mutationFn: (botId: string) => setActiveBot(botId),
    onSuccess: () => {
      toast.success("Active bot updated");
      queryClient.invalidateQueries({ queryKey: ["active-bot"] });
      queryClient.invalidateQueries({ queryKey: ["bot-profiles"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to set active bot");
    },
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["bot-profiles"] });
    if (activeBotId) {
      queryClient.invalidateQueries({ queryKey: ["bot-profile", activeBotId] });
    }
  };

  const selectedBot = useMemo<BotProfile | undefined>(() => {
    if (!activeBotId) return undefined;
    return bots.find((bot) => bot.id === activeBotId);
  }, [bots, activeBotId]);

  const isBusy = botsLoading || botsFetching || detailFetching || activationMutation.isPending;

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto w-full">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Manage bot profiles and version configurations
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={isBusy}>
          {isBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
          Refresh
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="border-border">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">Bot Profiles</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {bots.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No profiles have been provisioned yet. Seed a bot profile to begin.
                </p>
              )}

              {bots.map((bot) => (
                <button
                  key={bot.id}
                  type="button"
                  onClick={() => setSelectedBotId(bot.id)}
                  className={cn(
                    "w-full rounded-2xl border bg-gradient-to-br from-white/5 to-transparent p-4 text-left transition",
                    selectedBotId === bot.id
                      ? "border-primary/60 shadow-lg shadow-primary/10"
                      : "border-border hover:border-primary/50"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold">{bot.name}</h3>
                    <Badge variant={bot.status === "ready" ? "default" : "outline"} className="uppercase">
                      {bot.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Env: <span className="uppercase">{bot.environment}</span> • Engine: {bot.engineType}
                  </p>
                  <p className="mt-3 text-xs text-muted-foreground">
                    Active version:{" "}
                    {bot.activeVersion?.versionNumber ? (
                      <span className="font-medium text-white">v{bot.activeVersion.versionNumber}</span>
                    ) : (
                      "None"
                    )}
                  </p>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="border-border">
          <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
                Version History
              </CardTitle>
              {selectedBot ? (
                <p className="text-base font-semibold text-white">{selectedBot.name}</p>
              ) : (
                <p className="text-sm text-muted-foreground">Select a bot to inspect versions</p>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {detailFetching && (
              <div className="flex items-center gap-3 rounded-xl border border-border bg-muted px-4 py-3 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Fetching version metadata…
              </div>
            )}

            {!detailFetching && versions.length === 0 && (
              <p className="text-sm text-muted-foreground">No versions available for this bot yet.</p>
            )}

            {versions.length > 0 && (
              <div className="space-y-3">
                {versions.map((version) => {
                  const isActive = selectedBot?.activeVersionId === version.id;
                  return (
                    <div
                      key={version.id}
                      className="rounded-2xl border border-border bg-muted p-4 transition hover:border-white/15"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-3">
                            <p className="font-semibold text-white">Version v{version.versionNumber}</p>
                            <Badge variant={isActive ? "default" : "outline"} className="uppercase">
                              {isActive ? "Active" : version.status}
                            </Badge>
                          </div>
                          {version.notes && (
                            <p className="mt-1 text-sm text-muted-foreground">{version.notes}</p>
                          )}
                        </div>
                        <Button
                          variant={isActive ? "secondary" : "default"}
                          size="sm"
                          disabled={isActive || activationMutation.isPending || !selectedBot}
                          onClick={() =>
                            selectedBot &&
                            activationMutation.mutate({ botId: selectedBot.id, versionId: version.id })
                          }
                        >
                          {activationMutation.isPending && activationMutation.variables?.versionId === version.id ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : null}
                          {isActive ? "Active" : "Activate"}
                        </Button>
                      </div>
                      <Separator className="my-3 bg-white/10" />
                      <div className="grid gap-2 text-xs text-muted-foreground md:grid-cols-3">
                        <span>
                          Status: <span className="text-white">{version.status}</span>
                        </span>
                        <span>
                          Created: {version.createdAt ? new Date(version.createdAt).toLocaleString() : "—"}
                        </span>
                        <span>
                          Checksum:{" "}
                          <span className="font-mono text-[11px] text-white/80">
                            {version.checksum ? version.checksum.slice(0, 10) + "…" : "—"}
                          </span>
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

