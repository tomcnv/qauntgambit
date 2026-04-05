import { Card, CardHeader, CardTitle, CardDescription } from "../../../components/ui/card";
import ExchangeCredentials from "../../../components/exchange-credentials";
import SettingsPageLayout from "./layout";

export default function ExchangesSettingsPage() {
  return (
    <SettingsPageLayout
      title="Exchanges & Keys"
      description="API credentials, connection tests, and key rotation"
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle>Exchange Credentials</CardTitle>
            <CardDescription>
              Manage API keys for exchange connectivity. Trading parameters are configured per-bot in Bot Management.
            </CardDescription>
          </CardHeader>
        </Card>
        <ExchangeCredentials />
      </div>
    </SettingsPageLayout>
  );
}

