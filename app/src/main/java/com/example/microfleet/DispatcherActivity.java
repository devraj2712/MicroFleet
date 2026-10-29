package com.example.microfleet;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.example.microfleet.map.MapHelper;
import com.example.microfleet.model.BatchRouteItemDto;
import com.example.microfleet.model.DispatchCommitRequest;
import com.example.microfleet.model.DispatchCommitResponse;
import com.example.microfleet.model.DispatchPreviewResponse;
import com.example.microfleet.model.OrderDto;
import com.example.microfleet.model.RouteStopDto;
import com.example.microfleet.model.UserDto;
import com.example.microfleet.network.ApiClient;
import com.example.microfleet.network.ApiService;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;

import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class DispatcherActivity extends AppCompatActivity {

    private TextView mTextDispatcherEmail;
    private TextView mTextPendingOrdersCount;
    private TextView mTextAvailableRidersCount;
    private MaterialButton mButtonGeneratePreview;
    private MaterialButton mButtonResetDemo;
    private MaterialButton mButtonCommitPlan;
    private MaterialButton mButtonLogout;
    private ProgressBar mProgressDispatcher;
    private TextView mTextDispatcherMessage;

    private LinearLayout mLayoutPreviewResults;
    private TextView mTextPreviewId;
    private TextView mTextSummaryMetrics;
    private TextView mTextDistanceTimeMetrics;
    private MapView mMapView;
    private LinearLayout mContainerAssignedBatches;
    private MaterialCardView mCardUnassignedBatches;
    private TextView mTextUnassignedTitle;
    private TextView mTextUnassignedDetails;
    private TextView mTextBaselineComparison;

    private String mCurrentPreviewId = null;
    private List<String> mApprovedBatchIds = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        MapHelper.initOsmdroid(this);
        setContentView(R.layout.activity_dispatcher);

        mTextDispatcherEmail = findViewById(R.id.text_dispatcher_email);
        mTextPendingOrdersCount = findViewById(R.id.text_pending_orders_count);
        mTextAvailableRidersCount = findViewById(R.id.text_available_riders_count);
        mButtonGeneratePreview = findViewById(R.id.button_generate_preview);
        mButtonResetDemo = findViewById(R.id.button_reset_demo);
        mButtonCommitPlan = findViewById(R.id.button_commit_plan);
        mButtonLogout = findViewById(R.id.button_logout);
        mProgressDispatcher = findViewById(R.id.progress_dispatcher);
        mTextDispatcherMessage = findViewById(R.id.text_dispatcher_message);

        mLayoutPreviewResults = findViewById(R.id.layout_preview_results);
        mTextPreviewId = findViewById(R.id.text_preview_id);
        mTextSummaryMetrics = findViewById(R.id.text_summary_metrics);
        mTextDistanceTimeMetrics = findViewById(R.id.text_distance_time_metrics);
        mMapView = findViewById(R.id.map_dispatcher);
        mContainerAssignedBatches = findViewById(R.id.container_assigned_batches);
        mCardUnassignedBatches = findViewById(R.id.card_unassigned_batches);
        mTextUnassignedTitle = findViewById(R.id.text_unassigned_title);
        mTextUnassignedDetails = findViewById(R.id.text_unassigned_details);
        mTextBaselineComparison = findViewById(R.id.text_baseline_comparison);

        if (mMapView != null) {
            MapHelper.configureMapView(mMapView, MapHelper.MUMBAI_CENTER, 11.5);
        }

        UserDto user = ApiClient.getCurrentUser();
        if (user != null) {
            mTextDispatcherEmail.setText(user.getEmail() + " (" + user.getRole() + ")");
        }

        mButtonLogout.setOnClickListener(v -> {
            ApiClient.clearSession();
            Intent intent = new Intent(DispatcherActivity.this, LoginActivity.class);
            startActivity(intent);
            finish();
        });

        mButtonGeneratePreview.setOnClickListener(v -> generateDispatchPreview());
        if (mButtonResetDemo != null) {
            mButtonResetDemo.setOnClickListener(v -> resetDemoData());
        }
        mButtonCommitPlan.setOnClickListener(v -> commitDispatchPlan());

        fetchInitialStatus();
    }

    private void fetchInitialStatus() {
        ApiService api = ApiClient.getApiService();
        api.getOrders("PENDING").enqueue(new Callback<List<OrderDto>>() {
            @Override
            public void onResponse(Call<List<OrderDto>> call, Response<List<OrderDto>> response) {
                if (response.isSuccessful() && response.body() != null) {
                    mTextPendingOrdersCount.setText(String.valueOf(response.body().size()));
                } else {
                    mTextPendingOrdersCount.setText("0");
                }
            }

            @Override
            public void onFailure(Call<List<OrderDto>> call, Throwable t) {
                mTextPendingOrdersCount.setText("?");
            }
        });

        // Fetch available riders dynamically
        api.getRiders(true).enqueue(new Callback<List<com.example.microfleet.model.RiderDto>>() {
            @Override
            public void onResponse(Call<List<com.example.microfleet.model.RiderDto>> call, Response<List<com.example.microfleet.model.RiderDto>> response) {
                if (response.isSuccessful() && response.body() != null) {
                    mTextAvailableRidersCount.setText(response.body().size() + " Available");
                } else {
                    mTextAvailableRidersCount.setText("0 Available");
                }
            }

            @Override
            public void onFailure(Call<List<com.example.microfleet.model.RiderDto>> call, Throwable t) {
                mTextAvailableRidersCount.setText("? Available");
            }
        });
    }

    private void showLoading(boolean loading, String message) {
        mProgressDispatcher.setVisibility(loading ? View.VISIBLE : View.GONE);
        mButtonGeneratePreview.setEnabled(!loading);
        mButtonCommitPlan.setEnabled(!loading);
        if (message != null) {
            mTextDispatcherMessage.setText(message);
            mTextDispatcherMessage.setVisibility(View.VISIBLE);
        } else {
            mTextDispatcherMessage.setVisibility(View.GONE);
        }
    }

    private void generateDispatchPreview() {
        showLoading(true, "Executing Fuzzy Logic Urgency -> GA Batching -> ACO Routes -> RL Rider Assignment...");

        Map<String, Object> body = new HashMap<>();
        body.put("policy", "rl");

        ApiService api = ApiClient.getApiService();
        api.getDispatchPreview(body).enqueue(new Callback<DispatchPreviewResponse>() {
            @Override
            public void onResponse(Call<DispatchPreviewResponse> call, Response<DispatchPreviewResponse> response) {
                showLoading(false, null);
                if (response.isSuccessful() && response.body() != null) {
                    renderPreviewResults(response.body());
                } else {
                    Toast.makeText(DispatcherActivity.this, "Preview failed: " + response.message(), Toast.LENGTH_LONG).show();
                    mTextDispatcherMessage.setText("Error generating dispatch preview: " + response.message());
                    mTextDispatcherMessage.setVisibility(View.VISIBLE);
                }
            }

            @Override
            public void onFailure(Call<DispatchPreviewResponse> call, Throwable t) {
                showLoading(false, null);
                Toast.makeText(DispatcherActivity.this, "Network error: " + t.getMessage(), Toast.LENGTH_LONG).show();
                mTextDispatcherMessage.setText("Network error: " + t.getMessage());
                mTextDispatcherMessage.setVisibility(View.VISIBLE);
            }
        });
    }

    private void resetDemoData() {
        showLoading(true, "Resetting demo dataset with fresh relative deadlines (+120m, +180m)...");
        ApiService api = ApiClient.getApiService();
        api.resetDemoData().enqueue(new Callback<Map<String, Object>>() {
            @Override
            public void onResponse(Call<Map<String, Object>> call, Response<Map<String, Object>> response) {
                showLoading(false, null);
                if (response.isSuccessful() && response.body() != null) {
                    Map<String, Object> body = response.body();
                    Toast.makeText(DispatcherActivity.this,
                            "Demo reset complete! Seeded: " + body.get("orders_seeded") + " orders, " + body.get("merchants_seeded") + " merchants.",
                            Toast.LENGTH_LONG).show();
                    mLayoutPreviewResults.setVisibility(View.GONE);
                    fetchInitialStatus();
                } else {
                    Toast.makeText(DispatcherActivity.this, "Reset failed: " + response.message(), Toast.LENGTH_SHORT).show();
                }
            }

            @Override
            public void onFailure(Call<Map<String, Object>> call, Throwable t) {
                showLoading(false, null);
                Toast.makeText(DispatcherActivity.this, "Network error resetting demo: " + t.getMessage(), Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void renderPreviewResults(DispatchPreviewResponse preview) {
        mCurrentPreviewId = preview.getPreviewId();
        mApprovedBatchIds.clear();

        mLayoutPreviewResults.setVisibility(View.VISIBLE);
        mTextPreviewId.setText("Preview Draft: " + preview.getPreviewId() + " (Expires: " + preview.getExpiresAt() + ")");

        Map<String, Object> summary = preview.getSummary();
        if (summary != null) {
            Object cand = summary.get("total_candidate_batches");
            Object feas = summary.get("feasible_batches_count") != null ? summary.get("feasible_batches_count") : summary.get("feasible_batches");
            Object asgn = summary.get("assigned_batches_count") != null ? summary.get("assigned_batches_count") : summary.get("assigned_batches");
            Object unasgn = summary.get("unassigned_batches_count") != null ? summary.get("unassigned_batches_count") : summary.get("unassigned_batches");

            int assignedInt = 0;
            if (asgn instanceof Number) {
                assignedInt = ((Number) asgn).intValue();
            }

            mTextSummaryMetrics.setText(String.format(Locale.US,
                    "Candidate: %s | Feasible: %s | Assigned: %s | Unassigned: %s",
                    cand, feas, asgn, unasgn));

            String distText = (assignedInt > 0 && summary.get("total_distance_km") != null)
                    ? String.format(Locale.US, "%.1f km", ((Number) summary.get("total_distance_km")).doubleValue())
                    : "Not available";
            String durText = (assignedInt > 0 && summary.get("total_duration_minutes") != null)
                    ? String.format(Locale.US, "%.1f mins", ((Number) summary.get("total_duration_minutes")).doubleValue())
                    : "Not available";

            mTextDistanceTimeMetrics.setText(String.format(Locale.US,
                    "Total Distance: %s | Duration: %s | Policy: %s",
                    distText, durText,
                    preview.getPolicyName() != null ? preview.getPolicyName() : summary.get("selected_policy")));
        }

        // Render Assigned Batches
        mContainerAssignedBatches.removeAllViews();
        List<BatchRouteItemDto> assigned = preview.getAssignedBatches();
        if (assigned != null && !assigned.isEmpty()) {
            for (BatchRouteItemDto batch : assigned) {
                mApprovedBatchIds.add(batch.getBatchId());
                View card = createBatchCardView(batch);
                mContainerAssignedBatches.addView(card);
            }
        } else {
            TextView emptyText = new TextView(this);
            emptyText.setText("No batches were assigned by the fleet optimization policy.");
            emptyText.setTextColor(Color.parseColor("#64748B"));
            emptyText.setPadding(0, 8, 0, 8);
            mContainerAssignedBatches.addView(emptyText);
        }

        // Commit button guard
        if (mApprovedBatchIds.isEmpty()) {
            mButtonCommitPlan.setEnabled(false);
            mButtonCommitPlan.setText("Commit Disabled: 0 Feasible Batches Assigned");
            mButtonCommitPlan.setBackgroundColor(Color.parseColor("#94A3B8"));
        } else {
            mButtonCommitPlan.setEnabled(true);
            mButtonCommitPlan.setText(String.format(Locale.US, "Confirm & Commit Dispatch Plan (%d Batches)", mApprovedBatchIds.size()));
            mButtonCommitPlan.setBackgroundColor(Color.parseColor("#16A34A"));
        }

        // Render Map Overlays: Riders, Stops, and Road Polylines
        if (mMapView != null) {
            mMapView.getOverlays().clear();
            List<GeoPoint> allPoints = new ArrayList<>();

            // 3 Demo Riders at simulated origins
            GeoPoint r1Pt = new GeoPoint(19.0550, 72.8350);
            GeoPoint r2Pt = new GeoPoint(19.1136, 72.8697);
            GeoPoint r3Pt = new GeoPoint(18.9950, 72.8300);

            MapHelper.addMarker(mMapView, 19.0550, 72.8350, "Rider 1: R-MUM-01 (Bandra)", "Simulated Demo Location");
            MapHelper.addMarker(mMapView, 19.1136, 72.8697, "Rider 2: R-MUM-02 (Andheri)", "Simulated Demo Location");
            MapHelper.addMarker(mMapView, 18.9950, 72.8300, "Rider 3: R-MUM-03 (Lower Parel)", "Simulated Demo Location");

            allPoints.add(r1Pt);
            allPoints.add(r2Pt);
            allPoints.add(r3Pt);

            int[] routeColors = {
                    Color.parseColor("#2563EB"), // Rider 1: Blue
                    Color.parseColor("#16A34A"), // Rider 2: Green
                    Color.parseColor("#D97706"), // Rider 3: Amber
                    Color.parseColor("#7C3AED")  // Overflow: Purple
            };

            int colorIdx = 0;
            if (assigned != null) {
                for (BatchRouteItemDto batch : assigned) {
                    int color = routeColors[colorIdx % routeColors.length];
                    colorIdx++;

                    // Draw actual OSM road polyline
                    if (batch.getRouteCoordinates() != null && !batch.getRouteCoordinates().isEmpty()) {
                        MapHelper.drawRoutePolyline(mMapView, batch.getRouteCoordinates(), color, 8f);
                    }

                    // Plot numbered stops
                    if (batch.getStops() != null) {
                        int stopNum = 1;
                        for (RouteStopDto stop : batch.getStops()) {
                            GeoPoint stopPt = new GeoPoint(stop.getLatitude(), stop.getLongitude());
                            allPoints.add(stopPt);
                            String title = String.format(Locale.US, "Stop %d [%s]",
                                    stopNum++,
                                    stop.getStopType());
                            String snippet = String.format(Locale.US, "Order: %s | ETA: %.1f mins",
                                    stop.getOrderId(),
                                    stop.getExpectedArrivalMinutes());
                            MapHelper.addMarker(mMapView, stop.getLatitude(), stop.getLongitude(), title, snippet);
                        }
                    }
                }
            }

            MapHelper.zoomToPoints(mMapView, allPoints);
        }

        // Render Unassigned Batches
        List<BatchRouteItemDto> unassigned = preview.getUnassignedBatches();
        if (unassigned != null && !unassigned.isEmpty()) {
            mCardUnassignedBatches.setVisibility(View.VISIBLE);
            mTextUnassignedTitle.setText("Unassigned Batches (" + unassigned.size() + ")");
            StringBuilder sb = new StringBuilder();
            for (BatchRouteItemDto b : unassigned) {
                sb.append("• Batch ").append(b.getBatchId()).append(":\n  Reason: ")
                        .append(b.getReason() != null ? b.getReason() : "Infeasible constraints")
                        .append("\n  Metrics: Distance: Not available | Duration: Not available\n\n");
            }
            mTextUnassignedDetails.setText(sb.toString().trim());
        } else {
            mCardUnassignedBatches.setVisibility(View.GONE);
        }

        // Render Baseline Comparisons
        Map<String, Object> baselines = preview.getBaselineComparisons();
        if (baselines != null) {
            StringBuilder baseSb = new StringBuilder();
            for (Map.Entry<String, Object> entry : baselines.entrySet()) {
                String policyName = entry.getKey().toUpperCase();
                Object val = entry.getValue();
                if (val instanceof Map) {
                    Map<?, ?> stats = (Map<?, ?>) val;
                    Object asgnCount = stats.get("assigned_count") != null ? stats.get("assigned_count") : stats.get("assigned_batches");
                    Object unasgnCount = stats.get("unassigned_count") != null ? stats.get("unassigned_count") : stats.get("unassigned_batches");
                    Object rew = stats.get("episode_reward") != null ? stats.get("episode_reward") : stats.get("total_reward");

                    baseSb.append(String.format(Locale.US,
                            "[%s] Assigned: %s | Unassigned: %s | Dist: %.1f km | Reward: %.2f\n",
                            policyName,
                            asgnCount,
                            unasgnCount,
                            stats.get("total_distance_km") != null ? ((Number) stats.get("total_distance_km")).doubleValue() : 0.0,
                            rew != null ? ((Number) rew).doubleValue() : 0.0));
                }
            }
            mTextBaselineComparison.setText(baseSb.toString().trim());
        }
    }

    private View createBatchCardView(BatchRouteItemDto batch) {
        MaterialCardView card = new MaterialCardView(this);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, 10, 0, 10);
        card.setLayoutParams(lp);
        card.setRadius(16f);
        card.setCardElevation(4f);
        card.setStrokeColor(Color.parseColor("#E2E8F0"));
        card.setStrokeWidth(2);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(24, 24, 24, 24);

        // Batch Header
        TextView header = new TextView(this);
        header.setText(String.format("Batch: %s  ➜  Rider: %s (%s)",
                batch.getBatchId(),
                batch.getAssignedRiderName() != null ? batch.getAssignedRiderName() : "Rider",
                batch.getAssignedRiderId()));
        header.setTextColor(Color.parseColor("#0F172A"));
        header.setTextSize(14f);
        header.setTypeface(null, android.graphics.Typeface.BOLD);
        layout.addView(header);

        // Approach & Fleet Cost Stats
        TextView approachStats = new TextView(this);
        approachStats.setText(String.format(Locale.US,
                "Approach to Pickup: %.1f km (%.1f mins) | Total: %.1f km (%.1f mins) | Fleet Cost: %.1f",
                batch.getApproachDistanceKm(), batch.getApproachDurationMinutes(),
                batch.getTotalDistanceKm(), batch.getTotalDurationMinutes(),
                batch.getFleetCost()));
        approachStats.setTextColor(Color.parseColor("#3B82F6"));
        approachStats.setTextSize(12f);
        approachStats.setTypeface(null, android.graphics.Typeface.BOLD);
        approachStats.setPadding(0, 4, 0, 4);
        layout.addView(approachStats);

        // Explanation Block
        if (batch.getExplanation() != null && !batch.getExplanation().isEmpty()) {
            MaterialCardView explCard = new MaterialCardView(this);
            explCard.setCardBackgroundColor(Color.parseColor("#EFF6FF"));
            explCard.setStrokeColor(Color.parseColor("#BFDBFE"));
            explCard.setStrokeWidth(2);
            explCard.setRadius(12f);
            LinearLayout.LayoutParams explLp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            explLp.setMargins(0, 8, 0, 8);
            explCard.setLayoutParams(explLp);

            LinearLayout explLayout = new LinearLayout(this);
            explLayout.setOrientation(LinearLayout.VERTICAL);
            explLayout.setPadding(16, 12, 16, 12);

            TextView explTitle = new TextView(this);
            explTitle.setText("💡 Route-Aware Assignment Reason:");
            explTitle.setTextColor(Color.parseColor("#1E40AF"));
            explTitle.setTextSize(12f);
            explTitle.setTypeface(null, android.graphics.Typeface.BOLD);
            explLayout.addView(explTitle);

            TextView explBody = new TextView(this);
            explBody.setText(batch.getExplanation());
            explBody.setTextColor(Color.parseColor("#1E3A8A"));
            explBody.setTextSize(11f);
            explBody.setPadding(0, 4, 0, 0);
            explLayout.addView(explBody);

            explCard.addView(explLayout);
            layout.addView(explCard);
        }

        // Evaluated Alternatives Comparison
        if (batch.getEvaluatedAlternatives() != null && !batch.getEvaluatedAlternatives().isEmpty()) {
            TextView altTitle = new TextView(this);
            altTitle.setText("Candidate Rider Alternatives Evaluated:");
            altTitle.setTextColor(Color.parseColor("#334155"));
            altTitle.setTextSize(12f);
            altTitle.setTypeface(null, android.graphics.Typeface.BOLD);
            altTitle.setPadding(0, 6, 0, 4);
            layout.addView(altTitle);

            for (Map<String, Object> alt : batch.getEvaluatedAlternatives()) {
                TextView altView = new TextView(this);
                String rider = String.valueOf(alt.get("rider_id"));
                Object approach = alt.get("approach_distance_km");
                Object routeDist = alt.get("route_distance_km");
                Object cost = alt.get("fleet_cost");
                String reason = String.valueOf(alt.get("reason"));

                altView.setText(String.format(Locale.US,
                        " • Rider %s: Approach %s km | Route %s km | Cost %s | %s",
                        rider, approach, routeDist, cost, reason));
                altView.setTextColor(Color.parseColor("#475569"));
                altView.setTextSize(10.5f);
                layout.addView(altView);
            }
        }

        // Urgency scores
        if (batch.getUrgencyScores() != null && !batch.getUrgencyScores().isEmpty()) {
            TextView urgencyView = new TextView(this);
            StringBuilder ub = new StringBuilder("Fuzzy Urgency: ");
            for (Map.Entry<String, Double> uEntry : batch.getUrgencyScores().entrySet()) {
                ub.append(uEntry.getKey()).append("=").append(String.format(Locale.US, "%.2f", uEntry.getValue())).append(" ");
            }
            urgencyView.setText(ub.toString());
            urgencyView.setTextColor(Color.parseColor("#B45309"));
            urgencyView.setTextSize(11f);
            urgencyView.setPadding(0, 6, 0, 0);
            layout.addView(urgencyView);
        }

        // Ordered Stops
        TextView stopsTitle = new TextView(this);
        stopsTitle.setText("Ordered Route Stops:");
        stopsTitle.setTextColor(Color.parseColor("#1E293B"));
        stopsTitle.setTextSize(12f);
        stopsTitle.setTypeface(null, android.graphics.Typeface.BOLD);
        stopsTitle.setPadding(0, 8, 0, 4);
        layout.addView(stopsTitle);

        if (batch.getStops() != null) {
            int stopIdx = 1;
            for (RouteStopDto stop : batch.getStops()) {
                TextView stopView = new TextView(this);
                stopView.setText(String.format(Locale.US,
                        " %d. [%s] %s | Lat/Lng: %.4f, %.4f | ETA: %.1f min",
                        stopIdx++,
                        stop.getStopType(),
                        stop.getOrderId(),
                        stop.getLatitude(),
                        stop.getLongitude(),
                        stop.getExpectedArrivalMinutes()));
                stopView.setTextColor(Color.parseColor("#334155"));
                stopView.setTextSize(11f);
                layout.addView(stopView);
            }
        }

        card.addView(layout);
        return card;
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (mMapView != null) {
            mMapView.onResume();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (mMapView != null) {
            mMapView.onPause();
        }
    }

    private void commitDispatchPlan() {
        if (mCurrentPreviewId == null || mApprovedBatchIds.isEmpty()) {
            Toast.makeText(this, "No valid dispatch plan to commit.", Toast.LENGTH_SHORT).show();
            return;
        }

        showLoading(true, "Committing dispatch plan transactionally to operational database...");

        DispatchCommitRequest req = new DispatchCommitRequest(mCurrentPreviewId, mApprovedBatchIds);
        ApiService api = ApiClient.getApiService();
        api.commitDispatchPlan(req).enqueue(new Callback<DispatchCommitResponse>() {
            @Override
            public void onResponse(Call<DispatchCommitResponse> call, Response<DispatchCommitResponse> response) {
                showLoading(false, null);
                if (response.isSuccessful() && response.body() != null) {
                    DispatchCommitResponse commitResp = response.body();
                    Toast.makeText(DispatcherActivity.this,
                            "Dispatch plan committed! " + commitResp.getCommittedBatchesCount() + " batches assigned.",
                            Toast.LENGTH_LONG).show();

                    mTextDispatcherMessage.setText("SUCCESS: Committed " + commitResp.getCommittedBatchesCount()
                            + " batches and " + commitResp.getCommittedOrdersCount() + " orders. Riders can now start routes!");
                    mTextDispatcherMessage.setTextColor(Color.parseColor("#16A34A"));
                    mTextDispatcherMessage.setVisibility(View.VISIBLE);

                    mLayoutPreviewResults.setVisibility(View.GONE);
                    fetchInitialStatus();
                } else {
                    Toast.makeText(DispatcherActivity.this, "Commit failed: " + response.message(), Toast.LENGTH_LONG).show();
                    mTextDispatcherMessage.setText("Commit failed: " + response.message());
                    mTextDispatcherMessage.setTextColor(Color.parseColor("#DC2626"));
                    mTextDispatcherMessage.setVisibility(View.VISIBLE);
                }
            }

            @Override
            public void onFailure(Call<DispatchCommitResponse> call, Throwable t) {
                showLoading(false, null);
                Toast.makeText(DispatcherActivity.this, "Network error: " + t.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
    }
}
