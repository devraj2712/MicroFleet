package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class DispatchCommitRequest {
    @SerializedName("preview_id")
    private String previewId;

    @SerializedName("approved_batch_ids")
    private List<String> approvedBatchIds;

    public DispatchCommitRequest(String previewId, List<String> approvedBatchIds) {
        this.previewId = previewId;
        this.approvedBatchIds = approvedBatchIds;
    }

    public String getPreviewId() { return previewId; }
    public List<String> getApprovedBatchIds() { return approvedBatchIds; }
}
