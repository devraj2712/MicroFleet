package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

public class AssignedRouteDto {
    @SerializedName("batch_id")
    private String batchId;

    @SerializedName(value = "status", alternate = {"batch_status", "route_status"})
    private String status;

    @SerializedName("route_id")
    private String routeId;

    @SerializedName("rider_id")
    private String riderId;

    @SerializedName(value = "estimated_distance_km", alternate = {"total_distance_km"})
    private double totalDistanceKm;

    @SerializedName(value = "estimated_duration_minutes", alternate = {"total_duration_minutes"})
    private double totalDurationMinutes;

    @SerializedName(value = "ordered_stops", alternate = {"stops"})
    private List<RouteStopDto> stops;

    @SerializedName("orders")
    private List<OrderDto> orders;

    @SerializedName("route_coordinates")
    private List<List<Double>> routeCoordinates;

    public String getBatchId() { return batchId; }
    public String getStatus() { return status; }
    public String getBatchStatus() { return status; }
    public String getRouteId() { return routeId; }
    public String getRiderId() { return riderId; }
    public double getTotalDistanceKm() { return totalDistanceKm; }
    public double getTotalDurationMinutes() { return totalDurationMinutes; }
    public List<RouteStopDto> getStops() { return stops; }
    public List<OrderDto> getOrders() { return orders; }
    public List<List<Double>> getRouteCoordinates() { return routeCoordinates; }
}
