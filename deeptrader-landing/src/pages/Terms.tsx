import { Header } from "@/components/landing/Header";
import { Footer } from "@/components/landing/Footer";
import { AnimatedSection } from "@/components/AnimatedSection";

const Terms = () => {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container mx-auto px-4 lg:px-8 py-24 lg:py-32">
        <AnimatedSection animation="fade-up">
          <div className="max-w-3xl mx-auto">
            <h1 className="text-4xl font-display font-bold text-foreground mb-4">
              Terms of Service
            </h1>
            <p className="text-muted-foreground mb-12">
              Last updated: {new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
            </p>

            <div className="prose prose-neutral dark:prose-invert max-w-none space-y-8">
              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  1. Agreement to Terms
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  By accessing or using the QuantGambit platform ("Service") operated by QuantGambit Labs, LLC ("Company," "we," "us," or "our"), you agree to be bound by these Terms of Service. If you do not agree to these terms, do not use our Service.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  2. Description of Service
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  QuantGambit provides quantitative trading infrastructure for cryptocurrency futures, including bot deployment, risk management, decision observability, and replay analysis tools. Our platform connects to third-party exchanges via API to execute trading operations on your behalf.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  3. Eligibility
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  You must be at least 18 years old and legally permitted to engage in cryptocurrency trading in your jurisdiction to use our Service. By using the Service, you represent that you meet these requirements and are not prohibited from trading digital assets under applicable laws.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  4. Account Responsibilities
                </h2>
                <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
                  <li>You are responsible for maintaining the confidentiality of your account credentials</li>
                  <li>You must enable two-factor authentication for live trading environments</li>
                  <li>You are responsible for all activities under your account</li>
                  <li>You must notify us immediately of any unauthorized access</li>
                  <li>You agree to provide accurate and complete information</li>
                </ul>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  5. API Keys and Exchange Access
                </h2>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  To use our Service, you must provide valid API credentials for supported exchanges. You acknowledge and agree that:
                </p>
                <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
                  <li>We strongly recommend API keys with trading permissions only—no withdrawal access</li>
                  <li>You are solely responsible for the security of your exchange accounts</li>
                  <li>We are not liable for losses resulting from compromised exchange credentials</li>
                  <li>Trading operations are executed subject to exchange availability and limitations</li>
                </ul>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  6. Risk Disclosure
                </h2>
                <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4">
                  <p className="text-foreground font-semibold mb-2">Important Risk Warning</p>
                  <p className="text-muted-foreground text-sm">
                    Cryptocurrency trading involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results.
                  </p>
                </div>
                <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
                  <li>Cryptocurrency markets are highly volatile and may result in significant losses</li>
                  <li>Leveraged trading amplifies both gains and losses</li>
                  <li>Automated trading systems may malfunction or behave unexpectedly</li>
                  <li>You may lose more than your initial investment</li>
                  <li>QuantGambit does not provide financial, investment, or trading advice</li>
                  <li>You are solely responsible for your trading decisions and outcomes</li>
                </ul>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  7. Non-Custodial Service
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  QuantGambit is a non-custodial platform. We do not hold, control, or have access to your funds. All assets remain on your connected exchange accounts. We cannot make withdrawals or transfers from your exchange accounts.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  8. Service Availability
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  We strive to maintain high availability but do not guarantee uninterrupted service. The Service may be unavailable due to maintenance, upgrades, exchange outages, or circumstances beyond our control. We are not liable for losses resulting from service interruptions.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  9. Limitation of Liability
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  TO THE MAXIMUM EXTENT PERMITTED BY LAW, QUANTGAMBIT SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, DATA, OR OTHER INTANGIBLES, RESULTING FROM YOUR USE OF THE SERVICE, TRADING LOSSES, OR ANY CONDUCT OF THIRD PARTIES.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  10. Indemnification
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  You agree to indemnify and hold harmless QuantGambit, its affiliates, officers, directors, employees, and agents from any claims, damages, or expenses arising from your use of the Service, violation of these Terms, or infringement of any third-party rights.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  11. Termination
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  We may suspend or terminate your access to the Service at any time, with or without cause, with or without notice. Upon termination, your right to use the Service ceases immediately. Provisions that by their nature should survive termination shall survive.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  12. Modifications
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  We reserve the right to modify these Terms at any time. Material changes will be communicated via email or platform notification. Continued use of the Service after changes constitutes acceptance of the modified Terms.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  13. Governing Law
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  These Terms shall be governed by and construed in accordance with the laws of the State of Delaware, without regard to conflict of law principles.
                </p>
              </section>

              <section>
                <h2 className="text-2xl font-display font-semibold text-foreground mb-4">
                  14. Contact
                </h2>
                <p className="text-muted-foreground leading-relaxed">
                  For questions about these Terms, please contact us at{" "}
                  <a href="mailto:legal@quantgambit.com" className="text-primary hover:underline">
                    legal@quantgambit.com
                  </a>
                </p>
              </section>
            </div>
          </div>
        </AnimatedSection>
      </main>
      <Footer />
    </div>
  );
};

export default Terms;
