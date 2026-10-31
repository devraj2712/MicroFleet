package com.example.microfleet;

import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import com.example.microfleet.model.AuthTokenResponse;
import com.example.microfleet.model.AssignedRouteDto;
import com.example.microfleet.model.LoginRequest;
import com.example.microfleet.model.OrderDto;
import com.example.microfleet.model.RiderDto;
import com.example.microfleet.model.UserDto;
import com.example.microfleet.network.ApiClient;
import com.example.microfleet.network.ApiService;
import com.example.microfleet.map.MapHelper;
import com.example.microfleet.map.SchematicMapView;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/** Dispatcher fleet overview and development rider chooser. */
public class RiderFleetActivity extends AppCompatActivity {

    public static final String EXTRA_SIGN_IN_AS_SELECTED_RIDER = "sign_in_as_selected_rider";

    private TextView mTitle;
    private TextView mSummary;
    private ProgressBar mProgress;
    private LinearLayout mContent;
    private MaterialButton mBackButton;
    private MaterialButton mRefreshButton;
    private List<RiderDto> mRiders = new ArrayList<>();
    private RiderDto mSelectedRider;
    private boolean mChooserMode;
    private boolean mIsLoading;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_rider_fleet);

        mTitle = findViewById(R.id.text_fleet_title);
        mSummary = findViewById(R.id.text_fleet_summary);
        mProgress = findViewById(R.id.progress_fleet);
        mContent = findViewById(R.id.container_fleet_content);
        mBackButton = findViewById(R.id.button_fleet_back);
        mRefreshButton = findViewById(R.id.button_fleet_refresh);
        mChooserMode = getIntent().getBooleanExtra(EXTRA_SIGN_IN_AS_SELECTED_RIDER, false);

        mBackButton.setOnClickListener(v -> goBack());
        mRefreshButton.setOnClickListener(v -> {
            if (mSelectedRider == null) {
                loadRiders();
            } else {
                loadRiderDetails(mSelectedRider);
            }
        });

        if (mChooserMode) {
            mTitle.setText("Choose a Rider");
            mBackButton.setText("Back to login");
            mSummary.setText("Choose a rider to open their own delivery page.");
            loadRiders();
            return;
        }

        UserDto user = ApiClient.getCurrentUser();
        String role = user != null ? user.getRole() : null;
        if (role == null || !(role.equalsIgnoreCase("DISPATCHER") || role.equalsIgnoreCase("ADMIN"))) {
            mSummary.setText("Only dispatchers and admins can view the full rider fleet.");
            mRefreshButton.setVisibility(View.GONE);
            return;
        }
        loadRiders();
    }

    private void loadRiders() {
        mSelectedRider = null;
        mTitle.setText(mChooserMode ? "Choose a Rider" : "Rider Fleet");
        mBackButton.setText(mChooserMode ? "Back to login" : "Back to dispatcher");
        showLoading(true);
        mSummary.setText("Loading rider availability...");
        ApiClient.getApiService().getRiders(false).enqueue(new Callback<List<RiderDto>>() {
            @Override
            public void onResponse(Call<List<RiderDto>> call, Response<List<RiderDto>> response) {
                showLoading(false);
                if (!response.isSuccessful() || response.body() == null) {
                    mSummary.setText("Could not load riders. Please refresh and try again.");
                    return;
                }
                mRiders = response.body();
                renderRiderList();
            }

            @Override
            public void onFailure(Call<List<RiderDto>> call, Throwable t) {
                showLoading(false);
                mSummary.setText("Could not reach the server: " + t.getLocalizedMessage());
            }
        });
    }

    private void renderRiderList() {
        mContent.removeAllViews();
        int available = 0;
        for (RiderDto rider : mRiders) {
            if (rider.isAvailable()) available++;
        }
        int busy = mRiders.size() - available;
        String summary = String.format(Locale.US, "%d riders  •  %d available  •  %d busy",
                mRiders.size(), available, busy);
        mSummary.setText(mChooserMode
                ? summary + "\nSelect a rider to sign in and view only their deliveries."
                : summary);

        if (mRiders.isEmpty()) {
            addMessage("No riders are registered yet.");
            return;
        }

        for (RiderDto rider : mRiders) {
            MaterialCardView card = createCard();
            LinearLayout body = verticalContainer();
            body.setPadding(dp(14), dp(12), dp(14), dp(12));

            TextView name = makeText(rider.getDisplayName(), 17, Color.parseColor("#8B5CF6"), true);
            body.addView(name);
            TextView status = makeText(rider.isAvailable()
                    ? "AVAILABLE — ready for a delivery"
                    : "BUSY — delivering assigned orders", 13,
                    rider.isAvailable() ? Color.parseColor("#6EE7A8") : Color.parseColor("#FBBF24"), true);
            LinearLayout.LayoutParams statusParams = paramsWrap();
            statusParams.topMargin = dp(5);
            body.addView(status, statusParams);
            TextView id = makeText(rider.getId() + "  •  " + rider.getPackageCountCapacity() + " packages max",
                    12, Color.parseColor("#8E8AA6"), false);
            LinearLayout.LayoutParams idParams = paramsWrap();
            idParams.topMargin = dp(4);
            body.addView(id, idParams);
            card.addView(body);
            card.setOnClickListener(v -> {
                if (mIsLoading) return;
                if (mChooserMode) signInAsRider(rider);
                else loadRiderDetails(rider);
            });
            mContent.addView(card, cardParams());
        }
    }

    private void signInAsRider(RiderDto rider) {
        String email = getDemoRiderEmail(rider.getId());
        if (email == null) {
            mSummary.setText("This rider does not have a demo sign-in account yet.");
            return;
        }

        showLoading(true);
        mSummary.setText("Opening " + safe(rider.getDisplayName()) + "'s rider page...");
        ApiClient.getApiService().login(new LoginRequest(email, "password123"))
                .enqueue(new Callback<AuthTokenResponse>() {
                    @Override
                    public void onResponse(Call<AuthTokenResponse> call, Response<AuthTokenResponse> response) {
                        showLoading(false);
                        if (!response.isSuccessful() || response.body() == null || response.body().getUser() == null) {
                            mSummary.setText("Could not open this rider. Reset Demo Data, then try again.");
                            return;
                        }
                        AuthTokenResponse auth = response.body();
                        ApiClient.setSession(auth.getAccessToken(), auth.getUser().getEmail(), auth.getUser());
                        startActivity(new android.content.Intent(RiderFleetActivity.this, RiderActivity.class));
                        setResult(RESULT_OK);
                        finish();
                    }

                    @Override
                    public void onFailure(Call<AuthTokenResponse> call, Throwable t) {
                        showLoading(false);
                        mSummary.setText("Could not reach the server: " + t.getLocalizedMessage());
                    }
                });
    }

    private String getDemoRiderEmail(String riderId) {
        if (riderId == null || !riderId.startsWith("R-MUM-")) return null;
        String number = riderId.substring(riderId.lastIndexOf('-') + 1);
        if ("01".equals(number)) return "rider@microfleet.dev";
        try {
            int riderNumber = Integer.parseInt(number);
            return riderNumber >= 2 && riderNumber <= 5 ? "rider" + riderNumber + "@microfleet.dev" : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private void loadRiderDetails(RiderDto rider) {
        mSelectedRider = rider;
        mTitle.setText(rider.getDisplayName());
        mBackButton.setText("Back to fleet");
        showLoading(true);
        mSummary.setText(rider.isAvailable() ? "Available for a new delivery" : "Busy delivering orders");
        mContent.removeAllViews();

        ApiService api = ApiClient.getApiService();
        api.getAssignedRoutes(rider.getId()).enqueue(new Callback<List<AssignedRouteDto>>() {
            @Override
            public void onResponse(Call<List<AssignedRouteDto>> call, Response<List<AssignedRouteDto>> response) {
                showLoading(false);
                if (!response.isSuccessful() || response.body() == null) {
                    addMessage("Could not load this rider's deliveries. Please refresh and try again.");
                    return;
                }
                renderRiderDetails(rider, response.body());
            }

            @Override
            public void onFailure(Call<List<AssignedRouteDto>> call, Throwable t) {
                showLoading(false);
                addMessage("Could not reach the server: " + t.getLocalizedMessage());
            }
        });
    }

    private void renderRiderDetails(RiderDto rider, List<AssignedRouteDto> routes) {
        mContent.removeAllViews();
        boolean busy = !routes.isEmpty() || !rider.isAvailable();
        mSummary.setText(busy ? "Busy delivering orders" : "Available — no deliveries assigned");

        addRiderLocationMap(rider, routes);

        if (routes.isEmpty()) {
            addMessage(busy
                    ? "This rider is marked busy, but there are no active delivery details to show."
                    : "This rider is ready to accept an order.");
            return;
        }

        for (AssignedRouteDto route : routes) {
            MaterialCardView routeCard = createCard();
            LinearLayout routeBody = verticalContainer();
            routeBody.setPadding(dp(14), dp(12), dp(14), dp(12));
            routeBody.addView(makeText("Delivery route " + safe(route.getBatchId()), 16,
                    Color.parseColor("#8B5CF6"), true));
            TextView routeStatus = makeText("Status: " + safe(route.getStatus()), 13,
                    Color.parseColor("#FBBF24"), true);
            LinearLayout.LayoutParams statusParams = paramsWrap();
            statusParams.topMargin = dp(4);
            routeBody.addView(routeStatus, statusParams);

            List<OrderDto> orders = route.getOrders();
            if (orders == null || orders.isEmpty()) {
                TextView noOrders = makeText("No order details were returned for this route.", 13,
                        Color.parseColor("#8E8AA6"), false);
                LinearLayout.LayoutParams noOrderParams = paramsWrap();
                noOrderParams.topMargin = dp(8);
                routeBody.addView(noOrders, noOrderParams);
            } else {
                for (OrderDto order : orders) {
                    LinearLayout divider = new LinearLayout(this);
                    divider.setOrientation(LinearLayout.VERTICAL);
                    TextView orderTitle = makeText("Order " + safe(order.getId()), 14,
                            Color.parseColor("#F1EFFA"), true);
                    LinearLayout.LayoutParams orderTitleParams = paramsWrap();
                    orderTitleParams.topMargin = dp(10);
                    divider.addView(orderTitle, orderTitleParams);
                    divider.addView(makeText("Status: " + safe(order.getStatus())
                                    + "  •  Merchant: " + safe(order.getMerchantId()),
                            12, Color.parseColor("#BDB9D3"), false), paramsWrap());
                    divider.addView(makeText(String.format(Locale.US, "Delivery: %.4f, %.4f",
                                    order.getDeliveryLatitude(), order.getDeliveryLongitude()),
                            12, Color.parseColor("#BDB9D3"), false), paramsWrap());
                    routeBody.addView(divider);
                }
            }
            routeCard.addView(routeBody);
            mContent.addView(routeCard, cardParams());
        }
    }

    private void addRiderLocationMap(RiderDto rider, List<AssignedRouteDto> routes) {
        MaterialCardView card = createCard();
        card.setClickable(false);
        card.setFocusable(false);
        card.setRadius(dp(18));
        LinearLayout body = verticalContainer();
        body.setPadding(dp(14), dp(12), dp(14), dp(14));
        body.addView(makeText("Rider location & route", 16, Color.parseColor("#F1EFFA"), true));

        String latitude = String.format(Locale.US, "%.5f", rider.getCurrentLatitude());
        String longitude = String.format(Locale.US, "%.5f", rider.getCurrentLongitude());
        TextView locationNote = makeText("Last reported position: " + latitude + ", " + longitude
                + "  •  Demo location, not live GPS", 12, Color.parseColor("#BDB9D3"), false);
        LinearLayout.LayoutParams noteParams = paramsMatch();
        noteParams.topMargin = dp(5);
        body.addView(locationNote, noteParams);

        SchematicMapView map = new SchematicMapView(this);
        LinearLayout.LayoutParams mapParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(230));
        mapParams.topMargin = dp(10);
        map.setLayoutParams(mapParams);
        MapHelper.configureMapView(map,
                new org.osmdroid.util.GeoPoint(rider.getCurrentLatitude(), rider.getCurrentLongitude()), 13.0);
        MapHelper.addMarker(map, rider.getCurrentLatitude(), rider.getCurrentLongitude(),
                "Rider current location", rider.getDisplayName());

        List<org.osmdroid.util.GeoPoint> points = new ArrayList<>();
        points.add(new org.osmdroid.util.GeoPoint(rider.getCurrentLatitude(), rider.getCurrentLongitude()));
        if (routes != null) {
            int routeIndex = 1;
            for (AssignedRouteDto route : routes) {
                MapHelper.drawRoutePolyline(map, route.getRouteCoordinates(),
                        Color.parseColor("#B79BFF"), 8f);
                if (route.getRouteCoordinates() != null) {
                    for (List<Double> coordinate : route.getRouteCoordinates()) {
                        if (coordinate != null && coordinate.size() >= 2
                                && coordinate.get(0) != null && coordinate.get(1) != null) {
                            points.add(new org.osmdroid.util.GeoPoint(coordinate.get(0), coordinate.get(1)));
                        }
                    }
                }
                if (route.getStops() != null) {
                    for (com.example.microfleet.model.RouteStopDto stop : route.getStops()) {
                        org.osmdroid.util.GeoPoint point = new org.osmdroid.util.GeoPoint(
                                stop.getLatitude(), stop.getLongitude());
                        points.add(point);
                        MapHelper.addMarker(map, point.getLatitude(), point.getLongitude(),
                                "Stop " + routeIndex++, "Order " + safe(stop.getOrderId()));
                    }
                }
            }
        }
        body.addView(map);
        card.addView(body);
        mContent.addView(card, cardParams());
        map.getViewTreeObserver().addOnGlobalLayoutListener(new android.view.ViewTreeObserver.OnGlobalLayoutListener() {
            @Override
            public void onGlobalLayout() {
                if (map.getWidth() <= 0 || map.getHeight() <= 0) return;
                map.getViewTreeObserver().removeOnGlobalLayoutListener(this);
                MapHelper.zoomToPoints(map, points);
            }
        });
    }

    private void addMessage(String message) {
        TextView text = makeText(message, 14, Color.rgb(71, 85, 105), false);
        text.setGravity(Gravity.CENTER_VERTICAL);
        text.setPadding(dp(4), dp(12), dp(4), dp(12));
        mContent.addView(text, paramsMatch());
    }

    private MaterialCardView createCard() {
        MaterialCardView card = new MaterialCardView(this);
        card.setRadius(dp(10));
        card.setCardElevation(dp(2));
        card.setStrokeWidth(dp(1));
        card.setStrokeColor(Color.parseColor("#3A3449"));
        card.setCardBackgroundColor(Color.parseColor("#171521"));
        card.setClickable(true);
        card.setFocusable(true);
        return card;
    }

    private LinearLayout verticalContainer() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    private TextView makeText(String value, float size, int color, boolean bold) {
        TextView text = new TextView(this);
        text.setText(value == null ? "—" : value);
        text.setTextSize(size);
        text.setTextColor(color);
        if (bold) text.setTypeface(null, android.graphics.Typeface.BOLD);
        return text;
    }

    private void showLoading(boolean loading) {
        mIsLoading = loading;
        mProgress.setVisibility(loading ? View.VISIBLE : View.GONE);
        mRefreshButton.setEnabled(!loading);
    }

    private void goBack() {
        if (mSelectedRider == null) {
            finish();
        } else {
            mSelectedRider = null;
            renderRiderList();
        }
    }

    @Override
    public void onBackPressed() {
        if (mSelectedRider != null) {
            goBack();
        } else {
            super.onBackPressed();
        }
    }

    private String safe(String value) {
        return value == null || value.trim().isEmpty() ? "—" : value;
    }

    private LinearLayout.LayoutParams paramsWrap() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams paramsMatch() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.MATCH_PARENT);
    }

    private LinearLayout.LayoutParams cardParams() {
        LinearLayout.LayoutParams params = paramsWrap();
        params.bottomMargin = dp(10);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
