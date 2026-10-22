package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class MerchantDto {
    @SerializedName("id")
    private String id;

    @SerializedName("name")
    private String name;

    @SerializedName("merchant_type")
    private String merchantType;

    @SerializedName("pickup_latitude")
    private double pickupLatitude;

    @SerializedName("pickup_longitude")
    private double pickupLongitude;

    @SerializedName("is_active")
    private boolean isActive;

    public String getId() { return id; }
    public String getName() { return name; }
    public String getMerchantType() { return merchantType; }
    public double getPickupLatitude() { return pickupLatitude; }
    public double getPickupLongitude() { return pickupLongitude; }
    public boolean isActive() { return isActive; }

    @Override
    public String toString() {
        return name + " (" + merchantType + ")";
    }
}
