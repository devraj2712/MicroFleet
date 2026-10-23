package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class RouteStopDto {
    @SerializedName("order_id")
    private String orderId;

    @SerializedName("stop_type")
    private String stopType;

    @SerializedName("latitude")
    private double latitude;

    @SerializedName("longitude")
    private double longitude;

    @SerializedName("load_after")
    private double loadAfter;

    @SerializedName("expected_arrival_minutes")
    private double expectedArrivalMinutes;

    @SerializedName("deadline_iso")
    private String deadlineIso;

    @SerializedName("is_late")
    private boolean isLate;

    public String getOrderId() { return orderId; }
    public String getStopType() { return stopType; }
    public double getLatitude() { return latitude; }
    public double getLongitude() { return longitude; }
    public double getLoadAfter() { return loadAfter; }
    public double getExpectedArrivalMinutes() { return expectedArrivalMinutes; }
    public String getDeadlineIso() { return deadlineIso; }
    public boolean isLate() { return isLate; }
}
