package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class DispatchCommitResponse {
    @SerializedName("status")
    private String status;

    @SerializedName("preview_id")
    private String previewId;

    @SerializedName(value = "total_orders_dispatched", alternate = {"committed_orders_count"})
    private int committedOrdersCount;

    @SerializedName("committed_batches")
    private List<Object> committedBatches;

    @SerializedName("message")
    private String message;

    public String getStatus() { return status; }
    public String getPreviewId() { return previewId; }
    public int getCommittedBatchesCount() {
        return committedBatches != null ? committedBatches.size() : 0;
    }
    public int getCommittedOrdersCount() { return committedOrdersCount; }
    public String getMessage() { return message; }
}
