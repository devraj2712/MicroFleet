package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;
import java.util.Map;

public class BatchRouteItemDto {
    @SerializedName("batch_id")
    private String batchId;

    @SerializedName("assigned_rider_id")
    private String assignedRiderId;

    @SerializedName("assigned_rider_name")
    private String assignedRiderName;

    @SerializedName("order_ids")
    private List<String> orderIds;

    @SerializedName("total_weight_kg")
    private double totalWeightKg;

    @SerializedName(value = "total_distance_km", alternate = {"distance_km"})
    private double totalDistanceKm;

    @SerializedName(value = "total_duration_minutes", alternate = {"duration_minutes"})
    private double totalDurationMinutes;

    @SerializedName("route_feasible")
    private boolean routeFeasible;

    @SerializedName("all_deadlines_met")
    private boolean allDeadlinesMet;

    @SerializedName("stops")
    private List<RouteStopDto> stops;

    @SerializedName("urgency_scores")
    private Map<String, Double> urgencyScores;

    @SerializedName("reason")
    private String reason;

    @SerializedName("explanation")
    private String explanation;

    @SerializedName("approach_distance_km")
    private double approachDistanceKm;

    @SerializedName("approach_duration_minutes")
    private double approachDurationMinutes;

    @SerializedName("fleet_cost")
    private double fleetCost;

    @SerializedName("route_coordinates")
    private List<List<Double>> routeCoordinates;

    @SerializedName("evaluated_alternatives")
    private List<Map<String, Object>> evaluatedAlternatives;

    public String getBatchId() { return batchId; }
    public String getAssignedRiderId() { return assignedRiderId; }
    public String getAssignedRiderName() { return assignedRiderName; }
    public List<String> getOrderIds() { return orderIds; }
    public double getTotalWeightKg() { return totalWeightKg; }
    public double getTotalDistanceKm() { return totalDistanceKm; }
    public double getTotalDurationMinutes() { return totalDurationMinutes; }
    public boolean isRouteFeasible() { return routeFeasible; }
    public boolean isAllDeadlinesMet() { return allDeadlinesMet; }
    public List<RouteStopDto> getStops() { return stops; }
    public Map<String, Double> getUrgencyScores() { return urgencyScores; }
    public String getReason() { return reason; }
    public String getExplanation() { return explanation; }
    public double getApproachDistanceKm() { return approachDistanceKm; }
    public double getApproachDurationMinutes() { return approachDurationMinutes; }
    public double getFleetCost() { return fleetCost; }
    public List<List<Double>> getRouteCoordinates() { return routeCoordinates; }
    public List<Map<String, Object>> getEvaluatedAlternatives() { return evaluatedAlternatives; }
}
