package com.example.microfleet;

import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.example.microfleet.map.MapHelper;
import com.example.microfleet.model.OrderDto;
import com.example.microfleet.network.ApiClient;
import com.google.android.material.card.MaterialCardView;

import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;

import java.util.ArrayList;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class OrderListActivity extends AppCompatActivity {

    private TextView mTextOrdersCount;
    private Button mBtnRefreshOrders;
    private ProgressBar mProgressOrders;
    private LinearLayout mContainerError;
    private TextView mTextErrorMessage;
    private Button mBtnRetryOrders;
    private LinearLayout mContainerEmpty;
    private RecyclerView mRecyclerOrders;
    private MaterialCardView mCardOrdersMap;
    private MapView mMapView;

    private OrderAdapter mAdapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        MapHelper.initOsmdroid(this);
        setContentView(R.layout.activity_order_list);

        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setTitle(R.string.title_order_list);
        }

        mTextOrdersCount = findViewById(R.id.text_orders_count);
        mBtnRefreshOrders = findViewById(R.id.btn_refresh_orders);
        mProgressOrders = findViewById(R.id.progress_orders);
        mContainerError = findViewById(R.id.container_error);
        mTextErrorMessage = findViewById(R.id.text_error_message);
        mBtnRetryOrders = findViewById(R.id.btn_retry_orders);
        mContainerEmpty = findViewById(R.id.container_empty);
        mRecyclerOrders = findViewById(R.id.recycler_orders);
        mCardOrdersMap = findViewById(R.id.card_orders_map);
        mMapView = findViewById(R.id.map_orders_list);

        if (mMapView != null) {
            MapHelper.configureMapView(mMapView, MapHelper.MUMBAI_CENTER, 11.5);
        }

        mAdapter = new OrderAdapter();
        mRecyclerOrders.setLayoutManager(new LinearLayoutManager(this));
        mRecyclerOrders.setAdapter(mAdapter);

        mBtnRefreshOrders.setOnClickListener(v -> fetchOrders());
        mBtnRetryOrders.setOnClickListener(v -> fetchOrders());

        fetchOrders();
    }

    @Override
    public boolean onSupportNavigateUp() {
        finish();
        return true;
    }

    private void fetchOrders() {
        mProgressOrders.setVisibility(View.VISIBLE);
        mContainerError.setVisibility(View.GONE);
        mContainerEmpty.setVisibility(View.GONE);
        mRecyclerOrders.setVisibility(View.GONE);
        if (mCardOrdersMap != null) {
            mCardOrdersMap.setVisibility(View.GONE);
        }

        ApiClient.getApiService().getOrders(null).enqueue(new Callback<List<OrderDto>>() {
            @Override
            public void onResponse(Call<List<OrderDto>> call, Response<List<OrderDto>> response) {
                mProgressOrders.setVisibility(View.GONE);

                if (response.isSuccessful() && response.body() != null) {
                    List<OrderDto> orders = response.body();
                    mTextOrdersCount.setText("Orders (" + orders.size() + ")");

                    if (orders.isEmpty()) {
                        mContainerEmpty.setVisibility(View.VISIBLE);
                    } else {
                        mRecyclerOrders.setVisibility(View.VISIBLE);
                        mAdapter.setOrders(orders);

                        if (mCardOrdersMap != null && mMapView != null) {
                            mCardOrdersMap.setVisibility(View.VISIBLE);
                            mMapView.getOverlays().clear();
                            List<GeoPoint> points = new ArrayList<>();

                            for (OrderDto o : orders) {
                                GeoPoint pick = new GeoPoint(o.getPickupLatitude(), o.getPickupLongitude());
                                GeoPoint del = new GeoPoint(o.getDeliveryLatitude(), o.getDeliveryLongitude());
                                points.add(pick);
                                points.add(del);

                                MapHelper.addMarker(mMapView, o.getPickupLatitude(), o.getPickupLongitude(),
                                        "Pickup: " + o.getId(), "Merchant: " + o.getMerchantId());
                                MapHelper.addMarker(mMapView, o.getDeliveryLatitude(), o.getDeliveryLongitude(),
                                        "Delivery: " + o.getId() + " [" + o.getStatus() + "]",
                                        o.getPackageType() + " (" + o.getWeightKg() + "kg)");
                            }

                            MapHelper.zoomToPoints(mMapView, points);
                        }
                    }
                } else {
                    showErrorState("Server error: HTTP " + response.code());
                }
            }

            @Override
            public void onFailure(Call<List<OrderDto>> call, Throwable t) {
                mProgressOrders.setVisibility(View.GONE);
                showErrorState("Cannot load orders: " + t.getLocalizedMessage() +
                        "\nEnsure server is running.");
            }
        });
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

    private void showErrorState(String message) {
        mContainerError.setVisibility(View.VISIBLE);
        mTextErrorMessage.setText(message);
        mTextOrdersCount.setText("Orders (Error)");
    }
}
