import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { navItems } from "@/data/landingContent";
import quantGambitDark from "@/assets/quantgambit-dark.png";
import quantGambitLight from "@/assets/quantgambit-light.png";

export function Header() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 10);
    };
    window.addEventListener("scroll", handleScroll);
    
    // Check for dark mode
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains("dark"));
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    
    return () => {
      window.removeEventListener("scroll", handleScroll);
      observer.disconnect();
    };
  }, []);

  return (
    <header
      className={`sticky top-0 z-50 w-full transition-all duration-300 ${
        isScrolled
          ? "bg-background/80 backdrop-blur-xl border-b border-border shadow-sm"
          : "bg-transparent"
      }`}
    >
      <div className="container mx-auto flex h-20 items-center justify-between px-4 lg:px-8">
        {/* Logo */}
        <a href="/" className="flex items-center gap-2.5 group">
          <img 
            src={isDark ? quantGambitDark : quantGambitLight} 
            alt="QuantGambit" 
            className="h-10 w-auto transition-transform group-hover:scale-105"
          />
        </a>

        {/* Desktop Nav - Centered */}
        <nav className="hidden lg:flex items-center gap-8">
          {navItems.map((link) => 
            link.href.startsWith('/') ? (
              <Link
                key={link.label}
                to={link.href}
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors relative after:absolute after:bottom-0 after:left-0 after:h-0.5 after:w-0 after:bg-primary after:transition-all hover:after:w-full"
              >
                {link.label}
              </Link>
            ) : (
              <a
                key={link.label}
                href={link.href}
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors relative after:absolute after:bottom-0 after:left-0 after:h-0.5 after:w-0 after:bg-primary after:transition-all hover:after:w-full"
              >
                {link.label}
              </a>
            )
          )}
        </nav>

        {/* Desktop CTAs */}
        <div className="hidden lg:flex items-center gap-3">
          <Link to="/sign-in">
            <Button variant="ghost" size="sm" className="font-medium">
              Sign in
            </Button>
          </Link>
          <Link to="/request-access">
            <Button size="sm" className="font-medium shadow-lg shadow-primary/25">
              Request access
            </Button>
          </Link>
        </div>

        {/* Mobile Menu */}
        <Sheet>
          <SheetTrigger asChild className="lg:hidden">
            <Button variant="ghost" size="icon">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="right" className="w-full sm:w-80">
            <div className="flex flex-col gap-6 pt-8">
              <nav className="flex flex-col gap-4">
                {navItems.map((link) => 
                  link.href.startsWith('/') ? (
                    <Link
                      key={link.label}
                      to={link.href}
                      className="text-lg font-medium text-foreground hover:text-primary transition-colors"
                    >
                      {link.label}
                    </Link>
                  ) : (
                    <a
                      key={link.label}
                      href={link.href}
                      className="text-lg font-medium text-foreground hover:text-primary transition-colors"
                    >
                      {link.label}
                    </a>
                  )
                )}
              </nav>
              <div className="flex flex-col gap-3 pt-4 border-t border-border">
                <Link to="/sign-in">
                  <Button variant="outline" className="w-full font-medium">
                    Sign in
                  </Button>
                </Link>
                <Link to="/request-access">
                  <Button className="w-full font-medium">Request access</Button>
                </Link>
              </div>
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  );
}
