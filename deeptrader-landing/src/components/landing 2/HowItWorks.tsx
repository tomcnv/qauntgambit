import { useState } from "react";
import { AnimatedSection } from "@/components/AnimatedSection";
import { howItWorksSteps } from "@/data/landingContent";
import { cn } from "@/lib/utils";
import dashboardOverview from "@/assets/dashboard-overview.png";
import dashboardSignals from "@/assets/dashboard-signals.png";
import dashboardReplay from "@/assets/dashboard-replay.png";

const stepScreenshots = [
  dashboardOverview,
  dashboardOverview,
  dashboardSignals,
  dashboardSignals,
  dashboardReplay,
];

export function HowItWorks() {
  const [activeStep, setActiveStep] = useState(0);
  const currentStep = howItWorksSteps[activeStep];

  return (
    <section id="how-it-works" className="relative overflow-hidden py-24 lg:py-32 bg-background">
      <div className="container mx-auto px-4 lg:px-8">
        {/* Header */}
        <AnimatedSection animation="fade-up" className="text-center mb-12">
          <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">
            How It Works
          </p>
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-6">
            From research to production — in five steps
          </h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            A robust, auditable workflow from exchange connection to post-trade analysis.
          </p>
        </AnimatedSection>

        {/* Horizontal Tabs */}
        <AnimatedSection animation="fade-up" delay={100}>
          <div className="flex flex-wrap justify-center gap-2 mb-8">
            {howItWorksSteps.map((step, idx) => (
              <button
                key={step.number}
                onClick={() => setActiveStep(idx)}
                className={cn(
                  "px-5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 flex items-center gap-2",
                  activeStep === idx
                    ? "bg-primary text-primary-foreground shadow-lg shadow-primary/25"
                    : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <span className="font-mono text-xs opacity-70">{step.number}</span>
                {step.title}
              </button>
            ))}
          </div>
        </AnimatedSection>

        {/* Content */}
        <AnimatedSection animation="fade-up" delay={200}>
          <div className="grid lg:grid-cols-5 gap-8 lg:gap-12 items-start">
            {/* Screenshot - 3 cols */}
            <div className="lg:col-span-3">
              <div className="relative rounded-2xl overflow-hidden border border-border bg-card shadow-2xl">
                {/* Browser chrome */}
                <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50 bg-muted/30">
                  <div className="flex gap-1.5">
                    <div className="h-2.5 w-2.5 rounded-full bg-foreground/20" />
                    <div className="h-2.5 w-2.5 rounded-full bg-foreground/20" />
                    <div className="h-2.5 w-2.5 rounded-full bg-foreground/20" />
                  </div>
                  <div className="flex-1 flex justify-center">
                    <span className="text-xs text-muted-foreground font-mono">{currentStep.title}</span>
                  </div>
                </div>

                {/* Screenshot */}
                <div className="relative aspect-[16/10] overflow-hidden">
                  {stepScreenshots.map((src, idx) => (
                    <img
                      key={idx}
                      src={src}
                      alt={`Step ${idx + 1}: ${howItWorksSteps[idx].title}`}
                      className={cn(
                        "absolute inset-0 w-full h-full object-cover object-top transition-opacity duration-500",
                        activeStep === idx ? "opacity-100" : "opacity-0"
                      )}
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* Details - 2 cols */}
            <div className="lg:col-span-2 space-y-6">
              <div>
                <h3 className="text-2xl font-display font-semibold text-foreground mb-4">
                  {currentStep.title}
                </h3>
                <p className="text-muted-foreground mb-6">
                  {currentStep.description}
                </p>

                {/* Input/Output */}
                <div className="space-y-4">
                  <div className="p-4 rounded-lg bg-muted/50 border border-border">
                    <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold">Input</span>
                    <p className="text-sm text-foreground mt-1">{currentStep.input}</p>
                  </div>
                  <div className="p-4 rounded-lg bg-primary/5 border border-primary/20">
                    <span className="text-xs text-primary uppercase tracking-wider font-semibold">Output</span>
                    <p className="text-sm text-foreground mt-1">{currentStep.output}</p>
                  </div>
                </div>
              </div>

              <div className="pt-4">
                <p className="text-sm text-muted-foreground italic">
                  Same pipeline in backtest and live—no separate "demo logic."
                </p>
              </div>
            </div>
          </div>
        </AnimatedSection>
      </div>
    </section>
  );
}
