import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { useIntelligenceData } from "../../lib/api/hooks";

export default function IntelligencePage() {
  const { data, isFetching } = useIntelligenceData();
  const alerts = data?.alerts ?? [];
  const warnings = data?.warnings ?? [];

  const renderStream = (title: string, items: typeof alerts) => (
    <Card className="border-white/5 bg-black/40">
      <CardHeader>
        <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-muted-foreground">
        {items.length === 0 ? (
          <p>{isFetching ? "Refreshing telemetry…" : "No entries."}</p>
        ) : (
          items.map((item, idx) => (
            <div key={`${item.component}-${idx}`} className="rounded-2xl border border-white/5 bg-white/5 px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-white">{item.component}</span>
                <Badge variant={item.severity === "critical" ? "warning" : "outline"}>{item.severity}</Badge>
              </div>
              <p className="mt-1 text-base text-white">{item.message}</p>
              <p className="text-xs text-muted-foreground">{new Date(item.timestamp).toLocaleTimeString()}</p>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {renderStream("Critical Alerts", alerts)}
      {renderStream("Warnings & Info", warnings)}
    </div>
  );
}

