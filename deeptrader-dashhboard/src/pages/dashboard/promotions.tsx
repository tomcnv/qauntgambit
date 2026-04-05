import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import {
  usePromotions,
  usePromotionDetail,
  useConfigDiff,
  useBotProfiles,
} from "../../lib/api/hooks";
import {
  createPromotion,
  approvePromotion,
  rejectPromotion,
  completePromotion,
} from "../../lib/api/client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "../../lib/utils";
import {
  GitBranch,
  CheckCircle,
  XCircle,
  Loader2,
  Eye,
  ArrowRight,
  FileDiff,
} from "lucide-react";
import toast from "react-hot-toast";

const getStatusColor = (status: string) => {
  switch (status) {
    case "pending":
      return "border-yellow-400/30 bg-yellow-500/10 text-yellow-300";
    case "approved":
      return "border-blue-400/30 bg-blue-500/10 text-blue-300";
    case "rejected":
      return "border-red-400/30 bg-red-500/10 text-red-300";
    case "completed":
      return "border-emerald-400/30 bg-emerald-500/10 text-emerald-300";
    default:
      return "border-gray-400/30 bg-gray-500/10 text-gray-300";
  }
};

const getPromotionTypeLabel = (type: string) => {
  switch (type) {
    case "research_to_paper":
      return "Research → Paper";
    case "paper_to_live":
      return "Paper → Live";
    case "rollback":
      return "Rollback";
    default:
      return type;
  }
};

export default function PromotionsPage() {
  const [selectedPromotionId, setSelectedPromotionId] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [showCreateForm, setShowCreateForm] = useState(false);

  const [createParams, setCreateParams] = useState({
    promotionType: "research_to_paper" as "research_to_paper" | "paper_to_live" | "rollback",
    sourceEnvironment: "research",
    targetEnvironment: "paper",
    botProfileId: "",
    botVersionId: "",
  });

  const queryClient = useQueryClient();

  const { data: promotionsData, isLoading } = usePromotions({
    status: filterStatus || undefined,
  });
  const { data: promotionDetail } = usePromotionDetail(selectedPromotionId || "");
  const { data: botProfiles } = useBotProfiles();

  const promotions = promotionsData?.data || [];

  const createMutation = useMutation({
    mutationFn: createPromotion,
    onSuccess: () => {
      toast.success("Promotion created");
      queryClient.invalidateQueries({ queryKey: ["promotions"] });
      setShowCreateForm(false);
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to create promotion");
    },
  });

  const approveMutation = useMutation({
    mutationFn: approvePromotion,
    onSuccess: () => {
      toast.success("Promotion approved");
      queryClient.invalidateQueries({ queryKey: ["promotions"] });
      queryClient.invalidateQueries({ queryKey: ["promotion-detail"] });
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to approve promotion");
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => rejectPromotion(id, reason),
    onSuccess: () => {
      toast.success("Promotion rejected");
      queryClient.invalidateQueries({ queryKey: ["promotions"] });
      queryClient.invalidateQueries({ queryKey: ["promotion-detail"] });
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to reject promotion");
    },
  });

  const completeMutation = useMutation({
    mutationFn: completePromotion,
    onSuccess: () => {
      toast.success("Promotion completed");
      queryClient.invalidateQueries({ queryKey: ["promotions"] });
      queryClient.invalidateQueries({ queryKey: ["promotion-detail"] });
    },
    onError: (error: any) => {
      toast.error(error.message || "Failed to complete promotion");
    },
  });

  const handleCreate = () => {
    createMutation.mutate({
      promotionType: createParams.promotionType,
      sourceEnvironment: createParams.sourceEnvironment,
      targetEnvironment: createParams.targetEnvironment,
      botProfileId: createParams.botProfileId,
      botVersionId: createParams.botVersionId,
    });
  };

  if (selectedPromotionId && promotionDetail) {
    const promotion = promotionDetail.promotion;
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <Button variant="ghost" onClick={() => setSelectedPromotionId(null)}>
              ← Back
            </Button>
            <h1 className="mt-4 text-3xl font-semibold">Promotion Details</h1>
          </div>
        </div>

        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>{promotion.promotion_type}</CardTitle>
              <Badge className={getStatusColor(promotion.status)}>{promotion.status}</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Source</p>
                <p className="mt-1 text-white">{promotion.source_environment}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Target</p>
                <p className="mt-1 text-white">{promotion.target_environment}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Requested By</p>
                <p className="mt-1 text-white">{promotion.requested_by}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-muted-foreground">Created</p>
                <p className="mt-1 text-white">{new Date(promotion.created_at).toLocaleString()}</p>
              </div>
            </div>

            {promotion.status === "pending" && (
              <div className="flex gap-3 pt-4">
                <Button
                  onClick={() => approveMutation.mutate(promotion.id)}
                  disabled={approveMutation.isPending}
                  className="flex-1"
                >
                  {approveMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle className="mr-2 h-4 w-4" />
                  )}
                  Approve
                </Button>
                <Button
                  variant="outline"
                  onClick={() => rejectMutation.mutate({ id: promotion.id })}
                  disabled={rejectMutation.isPending}
                  className="flex-1"
                >
                  {rejectMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="mr-2 h-4 w-4" />
                  )}
                  Reject
                </Button>
              </div>
            )}

            {promotion.status === "approved" && (
              <div className="pt-4">
                <Button
                  onClick={() => completeMutation.mutate(promotion.id)}
                  disabled={completeMutation.isPending}
                  className="w-full"
                >
                  {completeMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <ArrowRight className="mr-2 h-4 w-4" />
                  )}
                  Complete Promotion
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Promotion Workflow</h1>
          <p className="text-sm text-muted-foreground">
            Manage bot configuration promotions across environments
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(!showCreateForm)}>
          <GitBranch className="mr-2 h-4 w-4" />
          New Promotion
        </Button>
      </div>

      {showCreateForm && (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Create Promotion
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="promotionType">Promotion Type</Label>
                <Select
                  id="promotionType"
                  options={[
                    { value: "research_to_paper", label: "Research → Paper" },
                    { value: "paper_to_live", label: "Paper → Live" },
                    { value: "rollback", label: "Rollback" },
                  ]}
                  value={createParams.promotionType}
                  onChange={(e) => {
                    const type = e.target.value as any;
                    setCreateParams({
                      ...createParams,
                      promotionType: type,
                      sourceEnvironment: type === "research_to_paper" ? "research" : type === "paper_to_live" ? "paper" : "live",
                      targetEnvironment: type === "research_to_paper" ? "paper" : type === "paper_to_live" ? "live" : "paper",
                    });
                  }}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="botProfile">Bot Profile</Label>
                <Select
                  id="botProfile"
                  options={[
                    { value: "", label: "Select bot profile" },
                    ...(botProfiles?.bots?.map((b) => ({ value: b.id, label: b.name })) || []),
                  ]}
                  value={createParams.botProfileId}
                  onChange={(e) => setCreateParams({ ...createParams, botProfileId: e.target.value })}
                />
              </div>
            </div>
            <div className="mt-4 flex gap-3">
              <Button onClick={handleCreate} disabled={createMutation.isPending || !createParams.botProfileId}>
                {createMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <GitBranch className="mr-2 h-4 w-4" />
                )}
                Create
              </Button>
              <Button variant="outline" onClick={() => setShowCreateForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="flex gap-4">
        <Select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          options={[
            { value: "", label: "All Statuses" },
            { value: "pending", label: "Pending" },
            { value: "approved", label: "Approved" },
            { value: "rejected", label: "Rejected" },
            { value: "completed", label: "Completed" },
          ]}
        />
      </div>

      {/* Promotions List */}
      {isLoading ? (
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : promotions.length === 0 ? (
        <Card className="border-white/5 bg-black/30">
          <CardContent className="p-8 text-center">
            <p className="text-sm text-muted-foreground">No promotions found</p>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-white/5 bg-black/30">
          <CardHeader>
            <CardTitle className="text-sm uppercase tracking-[0.4em] text-muted-foreground">
              Promotions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {promotions.map((promotion) => (
                <div
                  key={promotion.id}
                  className="flex items-center justify-between rounded-xl border border-white/5 bg-white/5 p-4 hover:bg-white/10 cursor-pointer"
                  onClick={() => setSelectedPromotionId(promotion.id)}
                >
                  <div className="flex items-center gap-4">
                    <GitBranch className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <p className="font-semibold text-white">{getPromotionTypeLabel(promotion.promotion_type)}</p>
                      <p className="text-sm text-muted-foreground">
                        {promotion.source_environment} → {promotion.target_environment}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge className={getStatusColor(promotion.status)}>{promotion.status}</Badge>
                    <Button variant="ghost" size="sm">
                      <Eye className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}





