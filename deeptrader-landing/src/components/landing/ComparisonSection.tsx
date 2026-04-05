import { Check, X, Minus } from "lucide-react";
import { AnimatedSection } from "@/components/AnimatedSection";
import { comparisonRows, comparisonCompetitors } from "@/data/landingContent";
import { cn } from "@/lib/utils";

function StatusIcon({ value }: { value: boolean | string }) {
  if (value === true) {
    return (
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/15">
        <Check className="h-5 w-5 text-emerald-500" strokeWidth={2.5} />
      </div>
    );
  }
  if (value === "partial") {
    return (
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/15">
        <Minus className="h-5 w-5 text-amber-500" strokeWidth={2.5} />
      </div>
    );
  }
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-rose-500/10">
      <X className="h-5 w-5 text-rose-400" strokeWidth={2.5} />
    </div>
  );
}

export function ComparisonSection() {
  return (
    <section className="py-24 lg:py-32 bg-muted/30">
      <div className="container mx-auto px-4 lg:px-8">
        <AnimatedSection animation="fade-up" className="text-center mb-16">
          <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">
            Comparison
          </p>
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-6">
            Engineered for execution teams—not hobby bots.
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            See what's included when you need traceability and control.
          </p>
        </AnimatedSection>

        <AnimatedSection animation="fade-up" delay={100}>
          <div className="bg-card rounded-2xl border border-border shadow-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[700px]">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left py-5 px-6 text-sm font-semibold text-foreground w-2/5">
                      Feature
                    </th>
                    {comparisonCompetitors.map((comp) => (
                      <th
                        key={comp.id}
                        className={cn(
                          "text-center py-5 px-4 text-sm font-semibold",
                          comp.highlight
                            ? "text-primary bg-primary/5"
                            : "text-muted-foreground"
                        )}
                      >
                        {comp.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {comparisonRows.map((row, idx) => (
                    <tr
                      key={row.feature}
                      className={cn(
                        "border-b border-border/50 last:border-0 transition-colors",
                        idx % 2 === 0 ? "bg-background" : "bg-muted/20"
                      )}
                    >
                      <td className="py-5 px-6 text-sm font-medium text-foreground">
                        {row.feature}
                      </td>
                      {comparisonCompetitors.map((comp) => (
                        <td
                          key={comp.id}
                          className={cn(
                            "py-5 px-4",
                            comp.highlight && "bg-primary/5"
                          )}
                        >
                          <div className="flex justify-center">
                            <StatusIcon
                              value={row[comp.id as keyof typeof row] as boolean | string}
                            />
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </AnimatedSection>

        <AnimatedSection animation="fade-up" delay={200} className="text-center mt-10 space-y-2">
          <p className="text-sm text-muted-foreground">
            QuantGambit focuses on <span className="text-foreground font-medium">operational correctness</span>, not signal marketplaces or copy trading.
          </p>
        </AnimatedSection>
      </div>
    </section>
  );
}
