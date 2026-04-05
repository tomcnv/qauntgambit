import { Brain, Users, Building } from "lucide-react";
import { AnimatedSection } from "@/components/AnimatedSection";

const personas = [
  {
    icon: Brain,
    title: "Solo Quant",
    headline: "Move faster without losing visibility",
    description:
      "Deploy and iterate on strategies with versioned profiles, real-time decision tracing, and deterministic replay — so you can experiment aggressively without flying blind.",
  },
  {
    icon: Users,
    title: "Small Quant Team",
    headline: "Collaborate without configuration chaos",
    description:
      "Share strategy profiles, enforce permissions, review changes, and trace incidents together — without relying on tribal knowledge or screenshots.",
  },
  {
    icon: Building,
    title: "Prop Desk",
    headline: "Governed execution at scale",
    description:
      "Run multiple strategies across exchanges with defined risk pools, audit trails, and full traceability — designed for operational discipline and oversight.",
  },
];

export function PersonasSection() {
  return (
    <section className="py-24 lg:py-32 bg-muted/30">
      <div className="container mx-auto px-4 sm:px-6 lg:px-8 max-w-7xl">
        <AnimatedSection className="text-center mb-16">
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-4">
            Who QuantGambit is built for
          </h2>
        </AnimatedSection>

        <div className="grid md:grid-cols-3 gap-8 lg:gap-12">
          {personas.map((persona, index) => (
            <AnimatedSection
              key={persona.title}
              delay={index * 100}
              className="text-center"
            >
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-primary/10 text-primary mb-6">
                <persona.icon className="w-7 h-7" />
              </div>
              <h3 className="text-xl font-semibold text-foreground mb-2">
                {persona.title}
              </h3>
              <p className="text-lg font-medium text-primary mb-3">
                {persona.headline}
              </p>
              <p className="text-muted-foreground leading-relaxed">
                {persona.description}
              </p>
            </AnimatedSection>
          ))}
        </div>

        <AnimatedSection delay={400} className="text-center mt-12">
          <p className="text-sm text-muted-foreground">
            QuantGambit scales from a single operator to multi-strategy desks without changing how you work.
          </p>
        </AnimatedSection>
      </div>
    </section>
  );
}
