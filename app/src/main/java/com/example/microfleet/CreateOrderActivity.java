package com.example.microfleet;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.example.microfleet.model.CreateOrderRequest;
import com.example.microfleet.model.MerchantDto;
import com.example.microfleet.model.OrderDto;
import com.example.microfleet.network.ApiClient;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

import org.osmdroid.events.MapEventsReceiver;
import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;
import org.osmdroid.views.overlay.MapEventsOverlay;
import org.osmdroid.views.overlay.Marker;
import com.example.microfleet.map.MapHelper;

public class CreateOrderActivity extends AppCompatActivity {

    private Spinner mSpinnerMerchants;
    private Spinner mSpinnerPackageType;
    private Spinner mSpinnerPriority;
    private TextView mTextPickupCoords;
    private TextView mTextNoMerchantsWarning;
    private TextView mTextMapInstruction;
    private EditText mEditDeliveryLat;
    private EditText mEditDeliveryLon;
    private EditText mEditWeight;
    private EditText mEditPackageCount;
    private EditText mEditHandling;
    private Button mBtnSampleCoords;
    private Button mBtnSubmitOrder;
    private Button mBtnModePickup;
    private Button mBtnModeDelivery;
    private ProgressBar mProgressMerchants;
    private ProgressBar mProgressSubmitting;

    private MapView mMapView;
    private Marker mPickupMarker;
    private Marker mDeliveryMarker;
    private boolean mIsSelectingDelivery = true; // true = destination, false = pickup
    private Double mCustomPickupLat = null;
    private Double mCustomPickupLon = null;

    private List<MerchantDto> mMerchantsList = new ArrayList<>();
    private MerchantDto mSelectedMerchant;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        MapHelper.initOsmdroid(this);
        setContentView(R.layout.activity_create_order);

        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setTitle(R.string.title_create_order);
        }

        mSpinnerMerchants = findViewById(R.id.spinner_merchants);
        mSpinnerPackageType = findViewById(R.id.spinner_package_type);
        mSpinnerPriority = findViewById(R.id.spinner_priority);
        mTextPickupCoords = findViewById(R.id.text_pickup_coords);
        mTextNoMerchantsWarning = findViewById(R.id.text_no_merchants_warning);
        mTextMapInstruction = findViewById(R.id.text_map_instruction);
        mEditDeliveryLat = findViewById(R.id.edit_delivery_lat);
        mEditDeliveryLon = findViewById(R.id.edit_delivery_lon);
        mEditWeight = findViewById(R.id.edit_weight);
        mEditPackageCount = findViewById(R.id.edit_package_count);
        mEditHandling = findViewById(R.id.edit_handling);
        mBtnSampleCoords = findViewById(R.id.btn_sample_coords);
        mBtnSubmitOrder = findViewById(R.id.btn_submit_order);
        mBtnModePickup = findViewById(R.id.btn_mode_pickup);
        mBtnModeDelivery = findViewById(R.id.btn_mode_delivery);
        mProgressMerchants = findViewById(R.id.progress_merchants);
        mProgressSubmitting = findViewById(R.id.progress_submitting);
        mMapView = findViewById(R.id.map_create_order);

        setupMap();
        setupModeButtons();
        setupLandmarkChips();
        setupStaticSpinners();
        setupSampleCoordinates();
        loadMerchants();

        mBtnSubmitOrder.setOnClickListener(v -> submitOrder());
    }

    private void setupMap() {
        if (mMapView != null) {
            MapHelper.configureMapView(mMapView, MapHelper.MUMBAI_CENTER, 12.0);

            MapEventsOverlay overlay = new MapEventsOverlay(new MapEventsReceiver() {
                @Override
                public boolean singleTapConfirmedHelper(GeoPoint p) {
                    handleLocationSelected(p.getLatitude(), p.getLongitude(), "Map Tap");
                    return true;
                }

                @Override
                public boolean longPressHelper(GeoPoint p) {
                    return false;
                }
            });
            mMapView.getOverlays().add(overlay);
        }
    }

    private void setupModeButtons() {
        if (mBtnModeDelivery != null && mBtnModePickup != null) {
            mBtnModeDelivery.setOnClickListener(v -> setSelectionMode(true));
            mBtnModePickup.setOnClickListener(v -> setSelectionMode(false));
            updateModeButtonUi();
        }
    }

    private void setSelectionMode(boolean isDelivery) {
        mIsSelectingDelivery = isDelivery;
        updateModeButtonUi();
    }

    private void updateModeButtonUi() {
        if (mIsSelectingDelivery) {
            if (mTextMapInstruction != null) {
                mTextMapInstruction.setText("MODE: Set Delivery Destination. Tap on the Mumbai map or a landmark chip.");
            }
        } else {
            if (mTextMapInstruction != null) {
                mTextMapInstruction.setText("MODE: Set Origin Pickup. Tap on the Mumbai map or select merchant from dropdown.");
            }
        }
    }

    private void setupLandmarkChips() {
        setupChip(R.id.chip_bandra, 19.0550, 72.8350, "Bandra");
        setupChip(R.id.chip_dadar, 19.0178, 72.8478, "Dadar");
        setupChip(R.id.chip_lower_parel, 18.9950, 72.8300, "Lower Parel");
        setupChip(R.id.chip_juhu, 19.1000, 72.8250, "Juhu");
        setupChip(R.id.chip_borivali, 19.2300, 72.8560, "Borivali");
        setupChip(R.id.chip_worli, 19.0150, 72.8150, "Worli");
    }

    private void setupChip(int resId, double lat, double lon, String name) {
        View chip = findViewById(resId);
        if (chip != null) {
            chip.setOnClickListener(v -> {
                handleLocationSelected(lat, lon, name);
                if (mMapView != null) {
                    mMapView.getController().animateTo(new GeoPoint(lat, lon));
                }
            });
        }
    }

    private void handleLocationSelected(double lat, double lon, String label) {
        GeoPoint point = new GeoPoint(lat, lon);
        if (mIsSelectingDelivery) {
            mEditDeliveryLat.setText(String.format(Locale.US, "%.5f", lat));
            mEditDeliveryLon.setText(String.format(Locale.US, "%.5f", lon));
            if (mDeliveryMarker == null && mMapView != null) {
                mDeliveryMarker = MapHelper.addMarker(mMapView, lat, lon, "Destination (" + label + ")", lat + ", " + lon);
            } else if (mDeliveryMarker != null) {
                mDeliveryMarker.setPosition(point);
                mDeliveryMarker.setTitle("Destination (" + label + ")");
                mMapView.invalidate();
            }
            Toast.makeText(this, "Destination set to " + label + " (" + String.format(Locale.US, "%.4f, %.4f", lat, lon) + ")", Toast.LENGTH_SHORT).show();
        } else {
            mCustomPickupLat = lat;
            mCustomPickupLon = lon;
            mTextPickupCoords.setText(String.format(Locale.US, "Pickup (%s): %.4f, %.4f", label, lat, lon));
            if (mPickupMarker == null && mMapView != null) {
                mPickupMarker = MapHelper.addMarker(mMapView, lat, lon, "Pickup (" + label + ")", lat + ", " + lon);
            } else if (mPickupMarker != null) {
                mPickupMarker.setPosition(point);
                mPickupMarker.setTitle("Pickup (" + label + ")");
                mMapView.invalidate();
            }
            Toast.makeText(this, "Pickup set to " + label + " (" + String.format(Locale.US, "%.4f, %.4f", lat, lon) + ")", Toast.LENGTH_SHORT).show();
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

    @Override
    public boolean onSupportNavigateUp() {
        finish();
        return true;
    }

    private void setupStaticSpinners() {
        // Package Types
        String[] packageTypes = {"PARCEL", "PERISHABLE", "FRAGILE", "MEDICAL"};
        ArrayAdapter<String> pkgAdapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, packageTypes);
        mSpinnerPackageType.setAdapter(pkgAdapter);

        // Priorities
        String[] priorities = {"STANDARD", "PREMIUM", "VIP"};
        ArrayAdapter<String> prioAdapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, priorities);
        mSpinnerPriority.setAdapter(prioAdapter);
    }

    private void setupSampleCoordinates() {
        // Preset sample Mumbai destinations
        final double[][] samples = {
                {19.0680, 72.8385}, // Bandra East
                {19.0120, 72.8310}, // Prabhadevi
                {18.9810, 72.8240}, // Mahalaxmi
                {19.0250, 72.8450}  // Matunga
        };
        final int[] idx = {0};

        mBtnSampleCoords.setOnClickListener(v -> {
            int current = idx[0] % samples.length;
            mEditDeliveryLat.setText(String.format(Locale.US, "%.4f", samples[current][0]));
            mEditDeliveryLon.setText(String.format(Locale.US, "%.4f", samples[current][1]));
            idx[0]++;
            Toast.makeText(this, "Filled Sample Destination", Toast.LENGTH_SHORT).show();
        });
    }

    private void loadMerchants() {
        mProgressMerchants.setVisibility(View.VISIBLE);
        mTextNoMerchantsWarning.setVisibility(View.GONE);
        mBtnSubmitOrder.setEnabled(false);

        ApiClient.getApiService().getMerchants(true).enqueue(new Callback<List<MerchantDto>>() {
            @Override
            public void onResponse(Call<List<MerchantDto>> call, Response<List<MerchantDto>> response) {
                mProgressMerchants.setVisibility(View.GONE);
                if (response.isSuccessful() && response.body() != null) {
                    mMerchantsList = response.body();
                    if (mMerchantsList.isEmpty()) {
                        mTextNoMerchantsWarning.setVisibility(View.VISIBLE);
                        mTextPickupCoords.setText("Pickup: No merchant available");
                    } else {
                        populateMerchantsSpinner();
                        mBtnSubmitOrder.setEnabled(true);
                    }
                } else {
                    showError("Failed to fetch merchants: HTTP " + response.code());
                }
            }

            @Override
            public void onFailure(Call<List<MerchantDto>> call, Throwable t) {
                mProgressMerchants.setVisibility(View.GONE);
                mTextNoMerchantsWarning.setVisibility(View.VISIBLE);
                mTextNoMerchantsWarning.setText("⚠️ Cannot reach backend at " + ApiClient.getBaseUrl() +
                        "\nEnsure server is running and demo data is seeded.");
            }
        });
    }

    private void populateMerchantsSpinner() {
        ArrayAdapter<MerchantDto> adapter = new ArrayAdapter<>(
                this,
                android.R.layout.simple_spinner_dropdown_item,
                mMerchantsList
        );
        mSpinnerMerchants.setAdapter(adapter);

        String loggedInMerchantId = ApiClient.getCurrentUser() != null ? ApiClient.getCurrentUser().getMerchantId() : null;
        if (loggedInMerchantId != null) {
            for (int i = 0; i < mMerchantsList.size(); i++) {
                if (loggedInMerchantId.equals(mMerchantsList.get(i).getId())) {
                    mSpinnerMerchants.setSelection(i);
                    break;
                }
            }
        }

        mSpinnerMerchants.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                mSelectedMerchant = mMerchantsList.get(position);
                double pLat = mSelectedMerchant.getPickupLatitude();
                double pLon = mSelectedMerchant.getPickupLongitude();
                mTextPickupCoords.setText(String.format(Locale.US,
                        "Pickup: %.4f, %.4f (%s)",
                        pLat,
                        pLon,
                        mSelectedMerchant.getName() != null ? mSelectedMerchant.getName() : mSelectedMerchant.getId()));

                if (mMapView != null) {
                    GeoPoint mPoint = new GeoPoint(pLat, pLon);
                    if (mPickupMarker == null) {
                        mPickupMarker = MapHelper.addMarker(mMapView, pLat, pLon,
                                mSelectedMerchant.getName() != null ? mSelectedMerchant.getName() : mSelectedMerchant.getId(),
                                "Merchant Origin");
                    } else {
                        mPickupMarker.setPosition(mPoint);
                        mPickupMarker.setTitle(mSelectedMerchant.getName() != null ? mSelectedMerchant.getName() : mSelectedMerchant.getId());
                        mMapView.invalidate();
                    }
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
                mSelectedMerchant = null;
            }
        });
    }

    private void submitOrder() {
        if (mSelectedMerchant == null) {
            showError("Please select a valid merchant.");
            return;
        }

        String latStr = mEditDeliveryLat.getText().toString().trim();
        String lonStr = mEditDeliveryLon.getText().toString().trim();
        String weightStr = mEditWeight.getText().toString().trim();
        String countStr = mEditPackageCount.getText().toString().trim();
        String handling = mEditHandling.getText().toString().trim();

        if (latStr.isEmpty() || lonStr.isEmpty() || weightStr.isEmpty() || countStr.isEmpty()) {
            showError("Please fill in all required coordinates and package fields.");
            return;
        }

        double lat, lon, weight;
        int count;

        try {
            lat = Double.parseDouble(latStr);
            lon = Double.parseDouble(lonStr);
            weight = Double.parseDouble(weightStr);
            count = Integer.parseInt(countStr);
        } catch (NumberFormatException e) {
            showError("Invalid numeric input in coordinates, weight, or count.");
            return;
        }

        if (lat < -90.0 || lat > 90.0 || lon < -180.0 || lon > 180.0) {
            showError("Coordinates must be valid (Lat: [-90, 90], Lon: [-180, 180]).");
            return;
        }

        if (weight <= 0.0) {
            showError("Weight must be greater than zero.");
            return;
        }

        if (count < 1) {
            showError("Package count must be at least 1.");
            return;
        }

        // Format ISO-8601 UTC deadline (now + 2 hours)
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.add(Calendar.HOUR_OF_DAY, 2);
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        sdf.setTimeZone(TimeZone.getTimeZone("UTC"));
        String deadlineIso = sdf.format(cal.getTime());

        String pkgType = mSpinnerPackageType.getSelectedItem().toString();
        String priority = mSpinnerPriority.getSelectedItem().toString();

        double pickupLat = (mCustomPickupLat != null) ? mCustomPickupLat : mSelectedMerchant.getPickupLatitude();
        double pickupLon = (mCustomPickupLon != null) ? mCustomPickupLon : mSelectedMerchant.getPickupLongitude();

        CreateOrderRequest request = new CreateOrderRequest(
                mSelectedMerchant.getId(),
                pickupLat,
                pickupLon,
                lat,
                lon,
                deadlineIso,
                pkgType,
                handling,
                weight,
                count,
                priority,
                1
        );

        mProgressSubmitting.setVisibility(View.VISIBLE);
        mBtnSubmitOrder.setEnabled(false);

        ApiClient.getApiService().createOrder(request).enqueue(new Callback<OrderDto>() {
            @Override
            public void onResponse(Call<OrderDto> call, Response<OrderDto> response) {
                mProgressSubmitting.setVisibility(View.GONE);
                mBtnSubmitOrder.setEnabled(true);

                if (response.isSuccessful() && response.body() != null) {
                    OrderDto created = response.body();
                    showSuccessDialog(created);
                } else {
                    showError("Order creation failed: HTTP " + response.code());
                }
            }

            @Override
            public void onFailure(Call<OrderDto> call, Throwable t) {
                mProgressSubmitting.setVisibility(View.GONE);
                mBtnSubmitOrder.setEnabled(true);
                showError("Network error submitting order: " + t.getLocalizedMessage());
            }
        });
    }

    private void showSuccessDialog(OrderDto order) {
        new AlertDialog.Builder(this)
                .setTitle("Order Created Successfully!")
                .setMessage("Order ID: " + order.getId() +
                        "\nMerchant: " + order.getMerchantId() +
                        "\nDestination: " + order.getDeliveryLatitude() + ", " + order.getDeliveryLongitude() +
                        "\nStatus: " + order.getStatus())
                .setPositiveButton("View Orders", (dialog, which) -> {
                    Intent intent = new Intent(CreateOrderActivity.this, OrderListActivity.class);
                    startActivity(intent);
                    finish();
                })
                .setNegativeButton("Create Another", (dialog, which) -> {
                    mEditHandling.setText("");
                })
                .setCancelable(false)
                .show();
    }

    private void showError(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
