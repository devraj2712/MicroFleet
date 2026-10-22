package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class CreateOrderRequest {
    @SerializedName("merchant_id")
    private String merchantId;

    @SerializedName("pickup_latitude")
    private Double pickupLatitude;

    @SerializedName("pickup_longitude")
    private Double pickupLongitude;

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

    public CreateOrderRequest(
            String merchantId,
            Double pickupLatitude,
            Double pickupLongitude,
            double deliveryLatitude,
            double deliveryLongitude,
            String deliveryDeadline,
            String packageType,
            String handlingRequirements,
            double weightKg,
            int packageCount,
            String customerPriority,
            int merchantPriority) {
        this.merchantId = merchantId;
        this.pickupLatitude = pickupLatitude;
        this.pickupLongitude = pickupLongitude;
        this.deliveryLatitude = deliveryLatitude;
        this.deliveryLongitude = deliveryLongitude;
        this.deliveryDeadline = deliveryDeadline;
        this.packageType = packageType;
        this.handlingRequirements = handlingRequirements;
        this.weightKg = weightKg;
        this.packageCount = packageCount;
        this.customerPriority = customerPriority;
        this.merchantPriority = merchantPriority;
    }

    public String getMerchantId() { return merchantId; }
    public double getDeliveryLatitude() { return deliveryLatitude; }
    public double getDeliveryLongitude() { return deliveryLongitude; }
    public String getDeliveryDeadline() { return deliveryDeadline; }
}
