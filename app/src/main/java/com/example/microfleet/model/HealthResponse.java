package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class HealthResponse {
    @SerializedName("status")
    private String status;

    @SerializedName("app")
    private String app;

    @SerializedName("version")
    private String version;

    @SerializedName("database")
    private String database;

    @SerializedName("timestamp")
    private String timestamp;

    public String getStatus() { return status; }
    public String getApp() { return app; }
    public String getVersion() { return version; }
    public String getDatabase() { return database; }
    public String getTimestamp() { return timestamp; }
}
