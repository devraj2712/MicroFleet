package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class RegisterRequest {
    @SerializedName("email")
    private String email;

    @SerializedName("password")
    private String password;

    @SerializedName("role")
    private String role;

    @SerializedName("merchant_name")
    private String merchantName;

    @SerializedName("merchant_address")
    private String merchantAddress;

    @SerializedName("merchant_latitude")
    private Double merchantLatitude;

    @SerializedName("merchant_longitude")
    private Double merchantLongitude;

    @SerializedName("rider_name")
    private String riderName;

    @SerializedName("rider_phone")
    private String riderPhone;

    @SerializedName("rider_vehicle_type")
    private String riderVehicleType;

    public RegisterRequest(String email, String password, String role) {
        this.email = email;
        this.password = password;
        this.role = role;
    }

    public void setMerchantDetails(String name, String address, Double lat, Double lng) {
        this.merchantName = name;
        this.merchantAddress = address;
        this.merchantLatitude = lat;
        this.merchantLongitude = lng;
    }

    public void setRiderDetails(String name, String phone, String vehicleType) {
        this.riderName = name;
        this.riderPhone = phone;
        this.riderVehicleType = vehicleType;
    }

    public String getEmail() { return email; }
    public String getPassword() { return password; }
    public String getRole() { return role; }
}
