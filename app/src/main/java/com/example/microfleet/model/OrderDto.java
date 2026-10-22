package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class OrderDto {
    @SerializedName("id")
    private String id;

    @SerializedName("merchant_id")
    private String merchantId;

    @SerializedName("pickup_latitude")
    private double pickupLatitude;

    @SerializedName("pickup_longitude")
    private double pickupLongitude;

    @SerializedName("delivery_latitude")
    private double deliveryLatitude;

    @SerializedName("delivery_longitude")
    private double deliveryLongitude;

    @SerializedName("delivery_deadline")
    private String deliveryDeadline;

    @SerializedName("package_type")
    private String packageType;

    @SerializedName("handling_requirements")
    private String handlingRequirements;

    @SerializedName("weight_kg")
    private double weightKg;

    @SerializedName("package_count")
    private int packageCount;

    @SerializedName("customer_priority")
    private String customerPriority;

    @SerializedName("merchant_priority")
    private int merchantPriority;

    @SerializedName("status")
    private String status;

    @SerializedName("created_at")
    private String createdAt;

    public String getId() { return id; }
    public String getMerchantId() { return merchantId; }
    public double getPickupLatitude() { return pickupLatitude; }
    public double getPickupLongitude() { return pickupLongitude; }
    public double getDeliveryLatitude() { return deliveryLatitude; }
    public double getDeliveryLongitude() { return deliveryLongitude; }
    public String getDeliveryDeadline() { return deliveryDeadline; }
    public String getPackageType() { return packageType; }
    public String getHandlingRequirements() { return handlingRequirements; }
    public double getWeightKg() { return weightKg; }
    public int getPackageCount() { return packageCount; }
    public String getCustomerPriority() { return customerPriority; }
    public int getMerchantPriority() { return merchantPriority; }
    public String getStatus() { return status; }
    public String getCreatedAt() { return createdAt; }
}
