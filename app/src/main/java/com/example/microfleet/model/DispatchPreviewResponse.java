package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;
import java.util.Map;

public class DispatchPreviewResponse {
    @SerializedName("preview_id")
    private String previewId;

    @SerializedName("expires_at")
    private String expiresAt;

    @SerializedName("status")
    private String status;

    @SerializedName("policy_name")
    private String policyName;

    @SerializedName("summary")
    private Map<String, Object> summary;

    @SerializedName(value = "assignments", alternate = {"assigned_batches"})
    private List<BatchRouteItemDto> assignedBatches;

    @SerializedName("unassigned_batches")
    private List<BatchRouteItemDto> unassignedBatches;

    @SerializedName("baseline_comparisons")
    private Map<String, Object> baselineComparisons;

    public String getPreviewId() { return previewId; }
    public String getExpiresAt() { return expiresAt; }
    public String getStatus() { return status; }
    public String getPolicyName() { return policyName; }
    public Map<String, Object> getSummary() { return summary; }
    public List<BatchRouteItemDto> getAssignedBatches() { return assignedBatches; }
    public List<BatchRouteItemDto> getUnassignedBatches() { return unassignedBatches; }
    public Map<String, Object> getBaselineComparisons() { return baselineComparisons; }
}
