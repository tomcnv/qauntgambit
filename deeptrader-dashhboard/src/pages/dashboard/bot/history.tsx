import { Navigate } from "react-router-dom";
import { useEnsurePinnedBotFromRoute } from "./_bot-route-utils";

export default function BotHistoryPage() {
  useEnsurePinnedBotFromRoute();
  return <Navigate to="/history" replace />;
}


