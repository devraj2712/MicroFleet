package com.example.microfleet;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.example.microfleet.map.MapHelper;
import com.example.microfleet.model.AssignedRouteDto;
import com.example.microfleet.model.OrderDto;
import com.example.microfleet.model.RouteStopDto;
import com.example.microfleet.model.UpdateOrderStatusRequest;
import com.example.microfleet.model.UserDto;
import com.example.microfleet.network.ApiClient;
import com.example.microfleet.network.ApiService;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;

import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class RiderActivity extends AppCompatActivity {

    private TextView mTextRiderTitle;
    private TextView mTextRiderSubtitle;
    private TextView mTextRoutesCount;
    private TextView mTextDeliveriesProgress;
    private MaterialButton mButtonRefreshRiderRoutes;
    private MaterialButton mButtonRiderLogout;
    private ProgressBar mProgressRider;
    private TextView mTextRiderStatusMessage;
    private TextView mTextRiderEmpty;
    private LinearLayout mContainerRiderRoutes;
    private MapView mMapView;

    private String mRiderId = "R-MUM-01"; // Default demo fallback

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        MapHelper.initOsmdroid(this);
        setContentView(R.layout.activity_rider);

        mTextRiderTitle = findViewById(R.id.text_rider_title);
        mTextRiderSubtitle = findViewById(R.id.text_rider_subtitle);
        mTextRoutesCount = findViewById(R.id.text_routes_count);
        mTextDeliveriesProgress = findViewById(R.id.text_deliveries_progress);
        mButtonRefreshRiderRoutes = findViewById(R.id.button_refresh_rider_routes);
        mButtonRiderLogout = findViewById(R.id.button_rider_logout);
        mProgressRider = findViewById(R.id.progress_rider);
        mTextRiderStatusMessage = findViewById(R.id.text_rider_status_message);
        mTextRiderEmpty = findViewById(R.id.text_rider_empty);
        mContainerRiderRoutes = findViewById(R.id.container_rider_routes);
        mMapView = findViewById(R.id.map_rider);

        if (mMapView != null) {
            MapHelper.configureMapView(mMapView, getRiderStartLocation(mRiderId), 12.0);
        }

        UserDto user = ApiClient.getCurrentUser();
        if (user != null) {
            mTextRiderTitle.setText("Rider Console");
            if (user.getRiderId() != null && !user.getRiderId().isEmpty()) {
                mRiderId = user.getRiderId();
            }
            mTextRiderSubtitle.setText(user.getEmail() + " | ID: " + mRiderId);
        }

        mButtonRiderLogout.setOnClickListener(v -> {
            ApiClient.clearSession();
            Intent intent = new Intent(RiderActivity.this, LoginActivity.class);
            startActivity(intent);
            finish();
        });

        mButtonRefreshRiderRoutes.setOnClickListener(v -> loadAssignedRoutes());

        loadAssignedRoutes();
    }

    private GeoPoint getRiderStartLocation(String riderId) {
        if ("R-MUM-02".equalsIgnoreCase(riderId)) {
            return new GeoPoint(19.1136, 72.8697); // Andheri East
        } else if ("R-MUM-03".equalsIgnoreCase(riderId)) {
            return new GeoPoint(18.9950, 72.8300); // Lower Parel
        }
        return new GeoPoint(19.0550, 72.8350); // Bandra West (R-MUM-01)
    }

    private void showLoading(boolean loading) {
        mProgressRider.setVisibility(loading ? View.VISIBLE : View.GONE);
        mButtonRefreshRiderRoutes.setEnabled(!loading);
    }

    private void loadAssignedRoutes() {
        showLoading(true);
        mTextRiderStatusMessage.setVisibility(View.GONE);

        ApiService api = ApiClient.getApiService();
        api.getAssignedRoutes(mRiderId).enqueue(new Callback<List<AssignedRouteDto>>() {
            @Override
            public void onResponse(Call<List<AssignedRouteDto>> call, Response<List<AssignedRouteDto>> response) {
                showLoading(false);
                if (response.isSuccessful() && response.body() != null) {
                    renderRoutes(response.body());
                } else {
                    mTextRiderStatusMessage.setText("Failed to load routes: " + response.message());
                    mTextRiderStatusMessage.setVisibility(View.VISIBLE);
                }
            }

            @Override
            public void onFailure(Call<List<AssignedRouteDto>> call, Throwable t) {
                showLoading(false);
                mTextRiderStatusMessage.setText("Network error: " + t.getMessage());
                mTextRiderStatusMessage.setVisibility(View.VISIBLE);
            }
        });
    }

    private void renderRoutes(List<AssignedRouteDto> routes) {
        mContainerRiderRoutes.removeAllViews();
        mTextRoutesCount.setText(String.valueOf(routes.size()));

        int totalDeliveries = 0;
        int completedDeliveries = 0;

        if (routes.isEmpty()) {
            mTextRiderEmpty.setVisibility(View.VISIBLE);
            mTextDeliveriesProgress.setText("0 / 0");
            return;
        }

        mTextRiderEmpty.setVisibility(View.GONE);

        for (AssignedRouteDto route : routes) {
            if (route.getOrders() != null) {
                totalDeliveries += route.getOrders().size();
                for (OrderDto o : route.getOrders()) {
                    if ("DELIVERED".equalsIgnoreCase(o.getStatus())) {
                        completedDeliveries++;
                    }
                }
            }

            View routeCard = createRouteCardView(route);
            mContainerRiderRoutes.addView(routeCard);
        }

        mTextDeliveriesProgress.setText(completedDeliveries + " / " + totalDeliveries);

        // Map Rendering of assigned route and stops
        if (mMapView != null) {
            mMapView.getOverlays().clear();
            GeoPoint riderOrigin = getRiderStartLocation(mRiderId);
            MapHelper.addMarker(mMapView, riderOrigin.getLatitude(), riderOrigin.getLongitude(),
                    "Rider Start (" + mRiderId + ")", "Configured Demo Location");

            List<GeoPoint> points = new ArrayList<>();
            points.add(riderOrigin);

            for (AssignedRouteDto route : routes) {
                if (route.getRouteCoordinates() != null && !route.getRouteCoordinates().isEmpty()) {
                    MapHelper.drawRoutePolyline(mMapView, route.getRouteCoordinates(), Color.parseColor("#2563EB"), 8f);
                }
                if (route.getStops() != null) {
                    int idx = 1;
                    for (RouteStopDto stop : route.getStops()) {
                        GeoPoint p = new GeoPoint(stop.getLatitude(), stop.getLongitude());
                        points.add(p);
                        MapHelper.addMarker(mMapView, stop.getLatitude(), stop.getLongitude(),
                                "Stop " + idx++ + " [" + stop.getStopType() + "]",
                                "Order: " + stop.getOrderId() + " | ETA: " + stop.getExpectedArrivalMinutes() + " mins");
                    }
                }
            }

            MapHelper.zoomToPoints(mMapView, points);
        }
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

    private View createRouteCardView(AssignedRouteDto route) {
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

        // Route Header
        TextView header = new TextView(this);
        header.setText("Batch " + route.getBatchId() + " (" + route.getBatchStatus() + ")");
        header.setTextColor(Color.parseColor("#0F172A"));
        header.setTextSize(15f);
        header.setTypeface(null, android.graphics.Typeface.BOLD);
        layout.addView(header);

        TextView details = new TextView(this);
        details.setText(String.format(Locale.US, "Distance: %.1f km | Est. Duration: %.1f mins",
                route.getTotalDistanceKm(), route.getTotalDurationMinutes()));
        details.setTextColor(Color.parseColor("#64748B"));
        details.setTextSize(12f);
        details.setPadding(0, 2, 0, 8);
        layout.addView(details);

        // Start Route Button (if not already dispatched or completed)
        if ("BATCHED".equalsIgnoreCase(route.getBatchStatus())) {
            MaterialButton startBtn = new MaterialButton(this);
            startBtn.setText("Start Delivery Route");
            startBtn.setBackgroundColor(Color.parseColor("#2563EB"));
            startBtn.setOnClickListener(v -> startRouteAction(route.getRouteId()));
            layout.addView(startBtn);
        }

        // Stops list
        if (route.getStops() != null && !route.getStops().isEmpty()) {
            TextView stopsTitle = new TextView(this);
            stopsTitle.setText("Ordered Delivery Itinerary:");
            stopsTitle.setTextColor(Color.parseColor("#334155"));
            stopsTitle.setTextSize(12f);
            stopsTitle.setTypeface(null, android.graphics.Typeface.BOLD);
            stopsTitle.setPadding(0, 8, 0, 4);
            layout.addView(stopsTitle);

            int stopIdx = 1;
            for (RouteStopDto stop : route.getStops()) {
                TextView stopView = new TextView(this);
                stopView.setText(String.format(Locale.US,
                        " %d. [%s] %s | Lat/Lng: %.4f, %.4f | ETA: %.1f min",
                        stopIdx++,
                        stop.getStopType(),
                        stop.getOrderId(),
                        stop.getLatitude(),
                        stop.getLongitude(),
                        stop.getExpectedArrivalMinutes()));
                stopView.setTextColor(Color.parseColor("#475569"));
                stopView.setTextSize(11f);
                layout.addView(stopView);
            }
        }

        // Orders list with status transition buttons
        if (route.getOrders() != null && !route.getOrders().isEmpty()) {
            TextView ordersTitle = new TextView(this);
            ordersTitle.setText("Orders in this Route:");
            ordersTitle.setTextColor(Color.parseColor("#334155"));
            ordersTitle.setTextSize(12f);
            ordersTitle.setTypeface(null, android.graphics.Typeface.BOLD);
            ordersTitle.setPadding(0, 10, 0, 4);
            layout.addView(ordersTitle);

            for (OrderDto order : route.getOrders()) {
                LinearLayout orderRow = new LinearLayout(this);
                orderRow.setOrientation(LinearLayout.VERTICAL);
                orderRow.setPadding(16, 12, 16, 12);
                orderRow.setBackgroundColor(Color.parseColor("#F8FAFC"));
                LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
                rowLp.setMargins(0, 6, 0, 6);
                orderRow.setLayoutParams(rowLp);

                TextView orderHeader = new TextView(this);
                orderHeader.setText(order.getId() + " - " + order.getStatus() + " (" + order.getWeightKg() + "kg)");
                orderHeader.setTextColor(Color.parseColor("#1E293B"));
                orderHeader.setTextSize(12f);
                orderHeader.setTypeface(null, android.graphics.Typeface.BOLD);
                orderRow.addView(orderHeader);

                // Action buttons based on current state
                if ("DISPATCHED".equalsIgnoreCase(order.getStatus()) || "BATCHED".equalsIgnoreCase(order.getStatus())) {
                    MaterialButton pickupBtn = new MaterialButton(this);
                    pickupBtn.setText("Mark Picked Up");
                    pickupBtn.setBackgroundColor(Color.parseColor("#0891B2")); // Cyan
                    pickupBtn.setOnClickListener(v -> updateOrderStatusAction(order.getId(), "PICKED_UP"));
                    orderRow.addView(pickupBtn);
                } else if ("PICKED_UP".equalsIgnoreCase(order.getStatus())) {
                    MaterialButton deliverBtn = new MaterialButton(this);
                    deliverBtn.setText("Mark Delivered");
                    deliverBtn.setBackgroundColor(Color.parseColor("#16A34A")); // Green
                    deliverBtn.setOnClickListener(v -> updateOrderStatusAction(order.getId(), "DELIVERED"));
                    orderRow.addView(deliverBtn);
                } else if ("DELIVERED".equalsIgnoreCase(order.getStatus())) {
                    TextView doneText = new TextView(this);
                    doneText.setText("✓ Delivered to Customer");
                    doneText.setTextColor(Color.parseColor("#16A34A"));
                    doneText.setTextSize(12f);
                    doneText.setTypeface(null, android.graphics.Typeface.BOLD);
                    orderRow.addView(doneText);
                }

                layout.addView(orderRow);
            }
        }

        card.addView(layout);
        return card;
    }

    private void startRouteAction(String routeId) {
        showLoading(true);
        ApiService api = ApiClient.getApiService();
        api.startRoute(mRiderId, routeId).enqueue(new Callback<Map<String, Object>>() {
            @Override
            public void onResponse(Call<Map<String, Object>> call, Response<Map<String, Object>> response) {
                showLoading(false);
                if (response.isSuccessful()) {
                    Toast.makeText(RiderActivity.this, "Route started! Orders are now Dispatched.", Toast.LENGTH_SHORT).show();
                    loadAssignedRoutes();
                } else {
                    Toast.makeText(RiderActivity.this, "Failed to start route: " + response.message(), Toast.LENGTH_LONG).show();
                }
            }

            @Override
            public void onFailure(Call<Map<String, Object>> call, Throwable t) {
                showLoading(false);
                Toast.makeText(RiderActivity.this, "Network error: " + t.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
    }

    private void updateOrderStatusAction(String orderId, String newStatus) {
        showLoading(true);
        ApiService api = ApiClient.getApiService();
        api.updateOrderStatus(orderId, new UpdateOrderStatusRequest(newStatus)).enqueue(new Callback<OrderDto>() {
            @Override
            public void onResponse(Call<OrderDto> call, Response<OrderDto> response) {
                showLoading(false);
                if (response.isSuccessful()) {
                    Toast.makeText(RiderActivity.this, "Order " + orderId + " -> " + newStatus, Toast.LENGTH_SHORT).show();
                    loadAssignedRoutes();
                } else {
                    Toast.makeText(RiderActivity.this, "Transition failed: " + response.message(), Toast.LENGTH_LONG).show();
                }
            }

            @Override
            public void onFailure(Call<OrderDto> call, Throwable t) {
                showLoading(false);
                Toast.makeText(RiderActivity.this, "Network error: " + t.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
    }
}
