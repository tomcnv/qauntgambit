import { Card, CardContent } from "../../components/ui/card";
import { useStatusNarrative } from "../../lib/api/hooks";
import { useScopeStore } from "../../store/scope-store";
import { Loader2 } from "lucide-react";

interface StatusNarrativeProps {
  timeWindow?: string;
}

export function StatusNarrative({ timeWindow = "15m" }: StatusNarrativeProps) {
  const { botId, exchangeAccountId } = useScopeStore();
  const { data, isLoading } = useStatusNarrative({ 
    timeWindow, 
    botId: botId || undefined, 
    exchangeAccountId: exchangeAccountId || undefined 
  });

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Generating status narrative...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <Card className="border-blue-500/20 bg-blue-500/5">
      <CardContent className="p-4">
        <div className="space-y-2">
          <div className="text-sm font-medium text-foreground">
            Status Narrative ({timeWindow})
          </div>
          <div className="text-sm text-muted-foreground leading-relaxed">
            {data.narrative}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}






