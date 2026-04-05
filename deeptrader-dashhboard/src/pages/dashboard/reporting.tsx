import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  useReportTemplates,
  useGeneratedReports,
  useCreateReportTemplate,
} from "../../lib/api/hooks";
import { cn } from "../../lib/utils";
import {
  FileText,
  Download,
  Calendar,
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  Plus,
  Settings,
} from "lucide-react";
import toast from "react-hot-toast";

const formatTime = (timestamp: string | number) => {
  const date = new Date(timestamp);
  return date.toLocaleString();
};

const formatDate = (date: string) => {
  return new Date(date).toLocaleDateString();
};

export default function ReportingPage() {
  const [showCreateTemplate, setShowCreateTemplate] = useState(false);
  const [filters, setFilters] = useState({
    reportType: "",
    status: "",
  });

  const { data: templatesData, isLoading: templatesLoading } = useReportTemplates({
    reportType: filters.reportType || undefined,
    enabled: true,
  });

  const { data: reportsData, isLoading: reportsLoading } = useGeneratedReports({
    reportType: filters.reportType || undefined,
    status: filters.status || undefined,
    limit: 50,
  });

  const createTemplateMutation = useCreateReportTemplate();

  const templates = templatesData?.data || [];
  const reports = reportsData?.data || [];

  const handleCreateTemplate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    
    try {
      await createTemplateMutation.mutateAsync({
        name: formData.get("name") as string,
        reportType: formData.get("reportType") as string,
        description: formData.get("description") as string,
        scheduleCron: formData.get("scheduleCron") as string || undefined,
        enabled: true,
        recipients: [],
        config: {},
      });
      
      toast.success("Report template created");
      setShowCreateTemplate(false);
      (e.target as HTMLFormElement).reset();
    } catch (error: any) {
      toast.error(error.message || "Failed to create template");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Automated Reports & Templates</h1>
          <p className="text-sm text-muted-foreground">
            Manage report templates and view generated reports
          </p>
        </div>
        <Button onClick={() => setShowCreateTemplate(true)}>
          <Plus className="h-4 w-4 mr-2" />
          New Template
        </Button>
      </div>

      {/* Filters */}
      <Card className="border-white/5 bg-black/30">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="reportType">Report Type</Label>
              <select
                id="reportType"
                className="flex h-11 w-full rounded-lg border border-white/10 bg-transparent px-4 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                value={filters.reportType}
                onChange={(e) => setFilters({ ...filters, reportType: e.target.value })}
              >
                <option value="">All Types</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="custom">Custom</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="status">Status</Label>
              <select
                id="status"
                className="flex h-11 w-full rounded-lg border border-white/10 bg-transparent px-4 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              >
                <option value="">All Statuses</option>
                <option value="generating">Generating</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Create Template Modal */}
      {showCreateTemplate && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Create Report Template
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateTemplate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Template Name</Label>
                <Input id="name" name="name" required placeholder="Daily Performance Report" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reportType">Report Type</Label>
                <select
                  id="reportType"
                  name="reportType"
                  required
                  className="flex h-11 w-full rounded-lg border border-white/10 bg-transparent px-4 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/60"
                >
                  <option value="">Select type</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Input
                  id="description"
                  name="description"
                  placeholder="Report description"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="scheduleCron">Schedule (Cron)</Label>
                <Input
                  id="scheduleCron"
                  name="scheduleCron"
                  placeholder="0 9 * * * (9 AM daily)"
                />
              </div>
              <div className="flex gap-2">
                <Button type="submit" disabled={createTemplateMutation.isPending}>
                  {createTemplateMutation.isPending ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Plus className="h-4 w-4 mr-2" />
                  )}
                  Create Template
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setShowCreateTemplate(false)}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Report Templates */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Report Templates ({templates.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {templatesLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : templates.length === 0 ? (
              <div className="py-8 text-center">
                <FileText className="mx-auto h-12 w-12 text-muted-foreground/50" />
                <p className="mt-2 text-sm text-muted-foreground">No templates found</p>
                <Button
                  variant="ghost"
                  className="mt-4"
                  onClick={() => setShowCreateTemplate(true)}
                >
                  Create your first template
                </Button>
              </div>
            ) : (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {templates.map((template) => (
                  <div
                    key={template.id}
                    className="rounded-lg border border-white/5 bg-white/5 p-3"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold text-white">{template.name}</h3>
                          <Badge variant="outline" className="text-xs">
                            {template.report_type}
                          </Badge>
                          {template.enabled ? (
                            <Badge className="bg-emerald-500/10 text-emerald-300 border-emerald-500/20">
                              Enabled
                            </Badge>
                          ) : (
                            <Badge className="bg-gray-500/10 text-gray-300 border-gray-500/20">
                              Disabled
                            </Badge>
                          )}
                        </div>
                        {template.description && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {template.description}
                          </p>
                        )}
                        {template.schedule_cron && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            Schedule: {template.schedule_cron}
                          </p>
                        )}
                        <p className="mt-1 text-xs text-muted-foreground">
                          Created: {formatTime(template.created_at)}
                        </p>
                      </div>
                      <Button variant="ghost" size="sm">
                        <Settings className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Generated Reports */}
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Generated Reports ({reports.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {reportsLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : reports.length === 0 ? (
              <div className="py-8 text-center">
                <FileText className="mx-auto h-12 w-12 text-muted-foreground/50" />
                <p className="mt-2 text-sm text-muted-foreground">No reports generated yet</p>
              </div>
            ) : (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {reports.map((report) => (
                  <div
                    key={report.id}
                    className="rounded-lg border border-white/5 bg-white/5 p-3"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">
                            {report.report_type}
                          </Badge>
                          {report.status === "completed" ? (
                            <Badge className="bg-emerald-500/10 text-emerald-300 border-emerald-500/20">
                              <CheckCircle className="h-3 w-3 mr-1" />
                              Completed
                            </Badge>
                          ) : report.status === "generating" ? (
                            <Badge className="bg-yellow-500/10 text-yellow-300 border-yellow-500/20">
                              <Clock className="h-3 w-3 mr-1" />
                              Generating
                            </Badge>
                          ) : (
                            <Badge className="bg-red-500/10 text-red-300 border-red-500/20">
                              <XCircle className="h-3 w-3 mr-1" />
                              Failed
                            </Badge>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Period: {formatDate(report.period_start)} → {formatDate(report.period_end)}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Generated: {formatTime(report.generated_at)}
                        </p>
                        {report.error_message && (
                          <p className="mt-1 text-xs text-red-400">{report.error_message}</p>
                        )}
                      </div>
                      {report.status === "completed" && (
                        <div className="flex gap-1">
                          {report.pdf_path && (
                            <Button variant="ghost" size="sm">
                              <Download className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}




