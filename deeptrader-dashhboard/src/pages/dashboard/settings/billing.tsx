import { CreditCard, FileText, Download } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import SettingsPageLayout from "./layout";

export default function BillingSettingsPage() {
  return (
    <SettingsPageLayout
      title="Billing & Plan"
      description="Subscription, invoices, and payment methods"
    >
      <div className="space-y-6">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              Current Plan
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between p-6 rounded-lg border border-primary/30 bg-primary/5">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-xl font-bold">Pro Plan</h3>
                  <Badge className="bg-primary/20 text-primary">Active</Badge>
                </div>
                <p className="text-sm text-muted-foreground">$99/month • Billed monthly</p>
              </div>
              <Button variant="outline">Upgrade</Button>
            </div>

            <div className="grid gap-4 md:grid-cols-3 mt-6">
              <div className="p-4 rounded-lg border border-border bg-muted/30">
                <p className="text-sm text-muted-foreground">Bots</p>
                <p className="text-2xl font-bold">3 / 10</p>
              </div>
              <div className="p-4 rounded-lg border border-border bg-muted/30">
                <p className="text-sm text-muted-foreground">Live Environments</p>
                <p className="text-2xl font-bold">1 / 2</p>
              </div>
              <div className="p-4 rounded-lg border border-border bg-muted/30">
                <p className="text-sm text-muted-foreground">Data Retention</p>
                <p className="text-2xl font-bold">1 year</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Billing Details
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
                <div>
                  <p className="font-medium">Payment Method</p>
                  <p className="text-sm text-muted-foreground">•••• •••• •••• 4242</p>
                </div>
                <Button variant="outline" size="sm">
                  Update
                </Button>
              </div>
              <div className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
                <div>
                  <p className="font-medium">Billing Email</p>
                  <p className="text-sm text-muted-foreground">billing@deeptrader.local</p>
                </div>
                <Button variant="outline" size="sm">
                  Change
                </Button>
              </div>
              <Button variant="outline" className="w-full">
                <Download className="h-4 w-4 mr-2" />
                Download Invoices
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle>Compare Plans</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              <PlanCard
                name="Starter"
                price="$29"
                features={["3 bots", "Paper trading only", "30 day retention", "Email support"]}
                current={false}
              />
              <PlanCard
                name="Pro"
                price="$99"
                features={["10 bots", "Live trading", "1 year retention", "Slack integration", "Priority support"]}
                current={true}
              />
              <PlanCard
                name="Enterprise"
                price="Custom"
                features={["Unlimited bots", "SSO/SAML", "Custom retention", "Dedicated support", "SLA"]}
                current={false}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </SettingsPageLayout>
  );
}

function PlanCard({
  name,
  price,
  features,
  current,
}: {
  name: string;
  price: string;
  features: string[];
  current: boolean;
}) {
  return (
    <div
      className={`p-4 rounded-lg border ${
        current ? "border-primary bg-primary/5" : "border-border bg-muted/30"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <h4 className="font-semibold">{name}</h4>
        {current && <Badge className="bg-primary/20 text-primary text-xs">Current</Badge>}
      </div>
      <p className="text-2xl font-bold mb-4">
        {price}
        <span className="text-sm font-normal text-muted-foreground">/mo</span>
      </p>
      <ul className="space-y-2 text-sm text-muted-foreground">
        {features.map((feature, i) => (
          <li key={i}>✓ {feature}</li>
        ))}
      </ul>
      {!current && (
        <Button variant="outline" size="sm" className="w-full mt-4">
          {name === "Enterprise" ? "Contact Sales" : "Upgrade"}
        </Button>
      )}
    </div>
  );
}

