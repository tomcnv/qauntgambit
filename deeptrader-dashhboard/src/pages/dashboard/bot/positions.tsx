import { Navigate } from "react-router-dom";
import { useEnsurePinnedBotFromRoute } from "./_bot-route-utils";

export default function BotPositionsPage() {
  useEnsurePinnedBotFromRoute();
  return <Navigate to="/positions" replace />;
}


