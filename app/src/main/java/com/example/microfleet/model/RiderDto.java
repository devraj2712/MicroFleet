package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class RiderDto {
    @SerializedName("id")
    private String id;

    @SerializedName("display_name")
    private String displayName;

    @SerializedName("current_latitude")
    private double currentLatitude;

    @SerializedName("current_longitude")
    private double currentLongitude;

    @SerializedName("weight_capacity_kg")
    private double weightCapacityKg;

    @SerializedName("package_count_capacity")
    private int packageCountCapacity;

    @SerializedName("is_available")
    private boolean isAvailable;

    public String getId() { return id; }
    public String getDisplayName() { return displayName; }
    public double getCurrentLatitude() { return currentLatitude; }
    public double getCurrentLongitude() { return currentLongitude; }
    public double getWeightCapacityKg() { return weightCapacityKg; }
    public int getPackageCountCapacity() { return packageCountCapacity; }
    public boolean isAvailable() { return isAvailable; }
}
