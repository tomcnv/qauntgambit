import { GitBranch, Eye, Shield, ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { AnimatedSection } from "@/components/AnimatedSection";
import { corePillars } from "@/data/landingContent";

const pillarIcons = {
  governance: GitBranch,
  observability: Eye,
  safety: Shield,
};

export function CorePillars() {
  return (
    <section className="py-24 lg:py-32 bg-muted/30">
      <div className="container mx-auto px-4 lg:px-8">
        <AnimatedSection animation="fade-up" className="text-center mb-16">
          <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">
            Core Pillars
          </p>
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-6">
            Operational discipline, by design
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Every feature designed with systematic traders in mind.
          </p>
        </AnimatedSection>

        <div className="grid md:grid-cols-3 gap-6 lg:gap-8">
          {corePillars.map((pillar, idx) => {
            const Icon = pillarIcons[pillar.id as keyof typeof pillarIcons];
            return (
              <AnimatedSection key={pillar.id} animation="fade-up" delay={idx * 100}>
                <Card className="bg-card border-border/60 hover:border-primary/30 hover:shadow-xl transition-all duration-300 h-full group">
                  <CardContent className="pt-8 pb-8 px-6">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 border border-primary/20 mb-6 group-hover:scale-110 transition-transform duration-300">
                      <Icon className="h-6 w-6 text-primary" />
                    </div>
                    <h3 className="text-xl font-display font-semibold text-foreground mb-4">
                      {pillar.title}
                    </h3>
                    <ul className="space-y-3 mb-6">
                      {pillar.features.map((feature, featureIdx) => (
                        <li key={featureIdx} className="flex items-start gap-3 text-sm text-muted-foreground">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary/60 mt-2 shrink-0" />
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>
                    <p className="text-sm font-medium text-foreground border-t border-border pt-4">
                      {pillar.outcome}
                    </p>
                    <a 
                      href={`#${pillar.id}`} 
                      className="inline-flex items-center text-sm font-medium text-primary mt-4 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      Learn more <ArrowRight className="h-4 w-4 ml-1" />
                    </a>
                  </CardContent>
                </Card>
              </AnimatedSection>
            );
          })}
        </div>
      </div>
    </section>
  );
}
