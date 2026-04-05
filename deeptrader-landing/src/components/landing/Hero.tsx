import { ArrowRight, Play } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ScreenshotFrame } from "./ScreenshotFrame";
import { AnimatedSection } from "@/components/AnimatedSection";
import { heroProofChips } from "@/data/landingContent";
import dashboardSignals from "@/assets/dashboard-signals.png";

const screenshots = [
  { src: dashboardSignals, label: "Live Signals" },
];

export function Hero() {
  return (
    <section className="relative min-h-[90vh] flex items-center py-24 lg:py-32 overflow-hidden">
      {/* QuantGambit hero gradient - subtle blue glow from top */}
      <div className="absolute inset-0 bg-gradient-hero pointer-events-none" />
      <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-primary/[0.08] rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-0 right-1/3 w-[400px] h-[400px] bg-primary/[0.04] rounded-full blur-[100px] pointer-events-none" />
      
      {/* Subtle grid overlay */}
      <div className="absolute inset-0 bg-grid-pattern opacity-[0.02] pointer-events-none" />
      
      <div className="container mx-auto px-4 lg:px-8 relative z-10">
        {/* Badge */}
        <AnimatedSection animation="fade-up" delay={0} className="text-center mb-6">
          <span className="inline-flex items-center px-4 py-1.5 rounded-full bg-primary/10 border border-primary/20 text-sm font-medium text-primary">
            Private beta · Built for serious futures operators
          </span>
        </AnimatedSection>

        {/* Headline */}
        <AnimatedSection animation="fade-up" delay={50} className="text-center mb-6">
          <h1 className="text-4xl sm:text-5xl lg:text-6xl xl:text-7xl font-display font-bold text-foreground leading-[1.05] tracking-tight max-w-4xl mx-auto">
            Quant-grade scalping{" "}
            <span className="text-primary">for crypto futures</span>
          </h1>
        </AnimatedSection>
        
        {/* Subheadline - max 2 lines */}
        <AnimatedSection animation="fade-up" delay={100} className="text-center mb-10">
          <p className="text-lg lg:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Deploy bots with versioned profiles, trace every decision in real time, and replay incidents end-to-end.
          </p>
        </AnimatedSection>

        {/* CTAs */}
        <AnimatedSection animation="fade-up" delay={200} className="text-center mb-8">
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link to="/request-access">
              <Button size="lg" className="gap-2 font-medium shadow-xl shadow-primary/20 hover:shadow-2xl hover:shadow-primary/25 transition-all text-base px-8">
                Request access
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link to="/request-access?type=demo">
              <Button variant="outline" size="lg" className="font-medium gap-2 text-base px-8 border-border/60 hover:bg-muted/50">
                <Play className="h-4 w-4" />
                Request a walkthrough
              </Button>
            </Link>
          </div>
        </AnimatedSection>

        {/* Proof Chips */}
        <AnimatedSection animation="fade-up" delay={300} className="mb-16">
          <div className="flex flex-wrap gap-3 justify-center">
            {heroProofChips.map((chip) => (
              <span
                key={chip}
                className="inline-flex items-center px-4 py-2 rounded-full bg-muted/60 border border-border/50 text-sm text-muted-foreground"
              >
                {chip}
              </span>
            ))}
          </div>
        </AnimatedSection>

        {/* Single Strong Screenshot */}
        <AnimatedSection animation="scale-in" delay={400} className="relative max-w-5xl mx-auto">
          <div className="relative">
            {/* Outer glow */}
            <div className="absolute -inset-4 bg-gradient-to-r from-primary/10 via-chart-2/10 to-primary/10 blur-3xl rounded-3xl opacity-60" />
            
            {/* Screenshot container */}
            <div className="relative rounded-2xl overflow-hidden shadow-2xl shadow-foreground/10 border border-border/40">
              <ScreenshotFrame images={screenshots} />
              
              {/* Callout pins - max 3 */}
              <div className="absolute top-[20%] left-[15%] hidden lg:flex items-center gap-2 bg-background/95 backdrop-blur-sm px-3 py-1.5 rounded-lg border border-border/60 shadow-lg">
                <span className="w-2 h-2 rounded-full bg-chart-3 animate-pulse" />
                <span className="text-xs font-medium text-foreground">Why not trading?</span>
              </div>
              
              <div className="absolute top-[40%] right-[10%] hidden lg:flex items-center gap-2 bg-background/95 backdrop-blur-sm px-3 py-1.5 rounded-lg border border-border/60 shadow-lg">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                <span className="text-xs font-medium text-foreground">Latency p95</span>
              </div>
              
              <div className="absolute bottom-[25%] left-[25%] hidden lg:flex items-center gap-2 bg-background/95 backdrop-blur-sm px-3 py-1.5 rounded-lg border border-border/60 shadow-lg">
                <span className="w-2 h-2 rounded-full bg-chart-2 animate-pulse" />
                <span className="text-xs font-medium text-foreground">Decision trace</span>
              </div>
            </div>
          </div>
        </AnimatedSection>
      </div>
    </section>
  );
}
