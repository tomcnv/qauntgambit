import { Header } from "@/components/landing/Header";
import { Hero } from "@/components/landing/Hero";
import { CorePillars } from "@/components/landing/CorePillars";
import { WhatIsQuantGambit } from "@/components/landing/WhatIsQuantGambit";
import { WorkbenchesSection } from "@/components/landing/WorkbenchesSection";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { ArchitectureSection } from "@/components/landing/ArchitectureSection";
import { PersonasSection } from "@/components/landing/PersonasSection";
import { ComparisonSection } from "@/components/landing/ComparisonSection";
import { SecuritySection } from "@/components/landing/SecuritySection";
import { FinalCTA } from "@/components/landing/FinalCTA";
import { Footer } from "@/components/landing/Footer";

const Index = () => {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main>
        <Hero />
        <CorePillars />
        <WhatIsQuantGambit />
        <WorkbenchesSection />
        <HowItWorks />
        <ArchitectureSection />
        <PersonasSection />
        <ComparisonSection />
        <SecuritySection />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
};

export default Index;
