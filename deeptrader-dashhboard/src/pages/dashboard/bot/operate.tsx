import { Navigate } from "react-router-dom";
import { useEnsurePinnedBotFromRoute } from "./_bot-route-utils";

export default function BotOperatePage() {
  useEnsurePinnedBotFromRoute();
  // No extra “tab system” UI: deep link pins bot, then sends you to the existing Operate page.
  return <Navigate to="/live" replace />;
}


