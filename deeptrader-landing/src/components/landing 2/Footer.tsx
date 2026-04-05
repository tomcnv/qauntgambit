import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Twitter, Github, Linkedin } from "lucide-react";
import { AnimatedSection } from "@/components/AnimatedSection";
import { footerLinks } from "@/data/landingContent";
import quantGambitDark from "@/assets/quantgambit-dark.png";
import quantGambitLight from "@/assets/quantgambit-light.png";

const socialLinks = [
  { icon: Twitter, href: "#", label: "Twitter" },
  { icon: Github, href: "#", label: "GitHub" },
  { icon: Linkedin, href: "#", label: "LinkedIn" },
];

export function Footer() {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains("dark"));
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return (
    <footer className="border-t border-border bg-background py-16 lg:py-20">
      <div className="container mx-auto px-4 lg:px-8">
        <AnimatedSection animation="fade-up">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-10 lg:gap-16">
            {/* Brand */}
            <div className="col-span-2 md:col-span-1">
              <a href="/" className="flex items-center gap-2.5 mb-6 group">
                <img 
                  src={isDark ? quantGambitDark : quantGambitLight} 
                  alt="QuantGambit" 
                  className="h-10 w-auto transition-transform group-hover:scale-105"
                />
              </a>
              <p className="text-sm text-muted-foreground mb-6 leading-relaxed">
                Quant-grade execution infrastructure for crypto futures.
              </p>
              <div className="flex gap-3">
                {socialLinks.map((social) => (
                  <a
                    key={social.label}
                    href={social.href}
                    className="flex h-10 w-10 items-center justify-center rounded-xl border border-border hover:bg-muted hover:border-primary/20 transition-all"
                    aria-label={social.label}
                  >
                    <social.icon className="h-4 w-4 text-muted-foreground" />
                  </a>
                ))}
              </div>
            </div>

            {/* Links */}
            {Object.entries(footerLinks).map(([category, links]) => (
              <div key={category}>
                <h4 className="font-display font-semibold text-foreground mb-5">{category}</h4>
                <ul className="space-y-3">
                  {links.map((link) => (
                    <li key={link.label}>
                      {link.href.startsWith('/') ? (
                        <Link
                          to={link.href}
                          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {link.label}
                        </Link>
                      ) : (
                        <a
                          href={link.href}
                          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {link.label}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </AnimatedSection>

        <AnimatedSection animation="fade-up" delay={100}>
          <div className="mt-16 pt-8 border-t border-border flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-muted-foreground">
              © {new Date().getFullYear()} QuantGambit Labs, LLC. All rights reserved.
            </p>
            <p className="text-xs text-muted-foreground">
              Built for systematic traders. Not financial advice.
            </p>
          </div>
        </AnimatedSection>
      </div>
    </footer>
  );
}
