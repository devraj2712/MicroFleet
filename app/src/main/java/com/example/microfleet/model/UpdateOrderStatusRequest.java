package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class UpdateOrderStatusRequest {
    @SerializedName(value = "status", alternate = {"new_status"})
    private String status;

    public UpdateOrderStatusRequest(String status) {
        this.status = status;
    }

    public String getStatus() { return status; }
}
