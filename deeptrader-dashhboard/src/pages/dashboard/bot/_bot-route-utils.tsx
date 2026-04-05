import { useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  useActiveConfig,
  useActivateBotExchangeConfig,
  useBotExchangeConfigs,
  useBotInstance,
} from "../../../lib/api/hooks";

/**
 * Ensures the server-side pinned bot matches the botId route param.
 * This is what makes deep links like /dashboard/bots/:botId/operate “just work”.
 */
export function useEnsurePinnedBotFromRoute() {
  const { botId } = useParams();
  const { data: activeConfigData } = useActiveConfig();
  const activateConfigMutation = useActivateBotExchangeConfig();
  const { data: botInstanceData } = useBotInstance(botId || "");
  const { data: exchangeConfigsData } = useBotExchangeConfigs(botId || "");

  useEffect(() => {
    if (!botId) return;
    const currentPinnedBotInstanceId = (activeConfigData as any)?.active?.bot_instance_id || null;
    if (currentPinnedBotInstanceId && currentPinnedBotInstanceId === botId) return;

    const configs = (exchangeConfigsData as any)?.configs || (botInstanceData as any)?.bot?.exchangeConfigs || (botInstanceData as any)?.exchangeConfigs || [];
    const config = configs.find((c: any) => c?.is_active) || configs[0] || null;
    if (!config?.id) return;

    // Pin the route bot by activating one of its exchange configs.
    activateConfigMutation.mutate({ botId, configId: config.id });
  }, [botId, activeConfigData, exchangeConfigsData, botInstanceData, activateConfigMutation]);

  return {
    botId: botId || null,
    isPinning: activateConfigMutation.isPending,
  };
}


