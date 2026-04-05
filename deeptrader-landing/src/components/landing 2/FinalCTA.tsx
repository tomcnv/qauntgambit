import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { AnimatedSection } from "@/components/AnimatedSection";

export function FinalCTA() {
  return (
    <section className="relative py-32 lg:py-40 overflow-hidden">
      {/* Elegant gradient background */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-chart-2/5 to-chart-5/5" />
      <div className="absolute inset-0 bg-gradient-stripe opacity-40" />
      
      {/* Decorative blobs */}
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-chart-2/10 rounded-full blur-3xl pointer-events-none" />
      
      <div className="container mx-auto px-4 lg:px-8 text-center relative z-10">
        <AnimatedSection animation="fade-up">
          <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-6 leading-tight">
            Talk to us about deploying QuantGambit
          </h2>
        </AnimatedSection>
        <AnimatedSection animation="fade-up" delay={100}>
          <p className="text-lg text-muted-foreground max-w-xl mx-auto mb-10">
            We onboard a limited number of teams. Tell us your venue, instruments, and operating model.
          </p>
        </AnimatedSection>
        <AnimatedSection animation="fade-up" delay={200}>
          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-6">
            <Link to="/request-access">
              <Button size="lg" className="gap-2 font-medium shadow-xl shadow-primary/25 hover:shadow-2xl hover:shadow-primary/30 transition-all">
                Request access
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link to="/request-access?type=sales">
              <Button size="lg" variant="outline" className="gap-2 font-medium bg-background/50 backdrop-blur-sm">
                Contact sales
              </Button>
            </Link>
          </div>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            We'll ask about your exchange, trading style, and deployment needs — then help you get set up.
          </p>
        </AnimatedSection>
        
        {/* Human signal */}
        <AnimatedSection animation="fade-up" delay={300}>
          <p className="text-xs text-muted-foreground/70 mt-12 max-w-lg mx-auto">
            QuantGambit is built by engineers and traders who have run automated strategies in live futures markets.
          </p>
        </AnimatedSection>
      </div>
    </section>
  );
}
