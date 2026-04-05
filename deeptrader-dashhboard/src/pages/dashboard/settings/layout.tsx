import { Link, useLocation } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { DashBar } from "../../../components/DashBar";

interface SettingsPageLayoutProps {
  title: string;
  description: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}

export default function SettingsPageLayout({
  title,
  description,
  children,
  actions,
}: SettingsPageLayoutProps) {
  return (
    <>
      <DashBar />
      <div className="p-6 space-y-6 max-w-[1200px] mx-auto">
      {/* Back + Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-start gap-4">
          <Button variant="ghost" size="sm" className="mt-0.5" asChild>
            <Link to="/settings">
              <ChevronLeft className="h-4 w-4 mr-1" />
              Settings
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>

      {/* Content */}
      {children}
      </div>
    </>
  );
}

