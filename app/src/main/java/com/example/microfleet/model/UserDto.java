package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class UserDto {
    @SerializedName("id")
    private String id;

    @SerializedName("email")
    private String email;

    @SerializedName("role")
    private String role;

    @SerializedName("merchant_id")
    private String merchantId;

    @SerializedName("rider_id")
    private String riderId;

    @SerializedName("is_active")
    private boolean isActive;

    public String getId() { return id; }
    public String getEmail() { return email; }
    public String getRole() { return role; }
    public String getMerchantId() { return merchantId; }
    public String getRiderId() { return riderId; }
    public boolean isActive() { return isActive; }
}
