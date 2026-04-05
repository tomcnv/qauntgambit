import { Navigate } from "react-router-dom";
import { useEnsurePinnedBotFromRoute } from "./_bot-route-utils";

export default function BotDecisionsPage() {
  useEnsurePinnedBotFromRoute();
  return <Navigate to="/signals" replace />;
}


