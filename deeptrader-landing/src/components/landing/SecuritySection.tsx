import { Link } from "react-router-dom";
import { KeyRound, Lock, Smartphone, FileCheck, Server, Shield, AlertTriangle, ChevronRight } from "lucide-react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { AnimatedSection } from "@/components/AnimatedSection";
import { securitySubsections, faqs } from "@/data/landingContent";

const securityIcons = [KeyRound, Lock, Smartphone, FileCheck, AlertTriangle];

export function SecuritySection() {
  return (
    <section id="security" className="py-24 lg:py-32 bg-muted/30">
      <div className="container mx-auto px-4 lg:px-8">
        <div className="grid lg:grid-cols-2 gap-16 lg:gap-24">
          {/* Left: Security Subsections */}
          <AnimatedSection animation="fade-up">
            <p className="text-sm font-semibold text-primary uppercase tracking-widest mb-4">Security</p>
            <h2 className="text-3xl lg:text-4xl xl:text-5xl font-display font-bold text-foreground mb-6">
              Enterprise-grade security
            </h2>
            <p className="text-lg font-medium text-foreground mb-4">
              Security is not a feature — it's a prerequisite.
            </p>
            <p className="text-muted-foreground mb-10 leading-relaxed">
              Built with institutional standards. Your keys, your control.
            </p>
            <ul className="space-y-6">
              {securitySubsections.map((section, idx) => {
                const Icon = securityIcons[idx % securityIcons.length];
                return (
                  <AnimatedSection key={section.title} animation="fade-up" delay={idx * 80}>
                    <li className="flex items-start gap-5 group">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-card border border-border group-hover:border-primary/30 transition-colors">
                        <Icon className="h-5 w-5 text-primary" />
                      </div>
                      <div>
                        <h4 className="font-semibold text-foreground mb-1">{section.title}</h4>
                        <p className="text-sm text-muted-foreground">{section.description}</p>
                      </div>
                    </li>
                  </AnimatedSection>
                );
              })}
            </ul>
            <Link 
              to="/security-controls" 
              className="inline-flex items-center gap-2 text-primary hover:underline mt-8 text-sm font-medium"
            >
              View Security & Controls Brief <ChevronRight className="h-4 w-4" />
            </Link>
          </AnimatedSection>

          {/* Right: FAQ */}
          <AnimatedSection animation="fade-up" delay={200}>
            <div className="bg-card rounded-2xl p-8 border border-border">
              <h3 className="text-xl font-display font-semibold text-foreground mb-8">
                Frequently asked questions
              </h3>
              <Accordion type="single" collapsible className="w-full">
                {faqs.slice(0, 6).map((faq, idx) => (
                  <AccordionItem key={idx} value={`item-${idx}`} className="border-border">
                    <AccordionTrigger className="text-left font-medium hover:text-primary transition-colors">
                      {faq.question}
                    </AccordionTrigger>
                    <AccordionContent className="text-muted-foreground leading-relaxed">
                      {faq.answer}
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </div>
          </AnimatedSection>
        </div>
      </div>
    </section>
  );
}
