package com.example.microfleet;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.example.microfleet.model.HealthResponse;
import com.example.microfleet.network.ApiClient;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class MainActivity extends AppCompatActivity {

    private TextView mTextStatusBadge;
    private TextView mTextConnectionDetails;
    private TextView mTextBaseUrl;
    private ProgressBar mProgressConnection;
    private Button mBtnRetryConnection;
    private Button mBtnCreateOrder;
    private Button mBtnViewOrders;
    private Button mBtnConfigureUrl;

    private boolean mHasAttemptedFallback = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mTextStatusBadge = findViewById(R.id.text_status_badge);
        mTextConnectionDetails = findViewById(R.id.text_connection_details);
        mTextBaseUrl = findViewById(R.id.text_base_url);
        mProgressConnection = findViewById(R.id.progress_connection);
        mBtnRetryConnection = findViewById(R.id.btn_retry_connection);
        mBtnCreateOrder = findViewById(R.id.btn_create_order);
        mBtnViewOrders = findViewById(R.id.btn_view_orders);
        mBtnConfigureUrl = findViewById(R.id.btn_configure_url);

        updateUrlDisplay();

        mBtnRetryConnection.setOnClickListener(v -> {
            mHasAttemptedFallback = false;
            checkBackendHealth();
        });
        mBtnCreateOrder.setOnClickListener(v -> {
            Intent intent = new Intent(MainActivity.this, CreateOrderActivity.class);
            startActivity(intent);
        });
        mBtnViewOrders.setOnClickListener(v -> {
            Intent intent = new Intent(MainActivity.this, OrderListActivity.class);
            startActivity(intent);
        });
        mBtnConfigureUrl.setOnClickListener(v -> showConfigureUrlDialog());

        checkBackendHealth();
    }

    @Override
    protected void onResume() {
        super.onResume();
        checkBackendHealth();
    }

    private void updateUrlDisplay() {
        mTextBaseUrl.setText("Server URL: " + ApiClient.getBaseUrl());
    }

    private void checkBackendHealth() {
        mProgressConnection.setVisibility(View.VISIBLE);
        mTextStatusBadge.setVisibility(View.GONE);
        mBtnRetryConnection.setVisibility(View.GONE);
        mTextConnectionDetails.setText("Connecting to " + ApiClient.getBaseUrl() + "health...");

        ApiClient.getApiService().getHealth().enqueue(new Callback<HealthResponse>() {
            @Override
            public void onResponse(Call<HealthResponse> call, Response<HealthResponse> response) {
                mProgressConnection.setVisibility(View.GONE);
                mTextStatusBadge.setVisibility(View.VISIBLE);

                if (response.isSuccessful() && response.body() != null) {
                    HealthResponse health = response.body();
                    mTextStatusBadge.setText("ONLINE");
                    mTextStatusBadge.getBackground().setTint(Color.parseColor("#10B981")); // Emerald
                    mTextConnectionDetails.setText("Connected to " + health.getApp() +
                            " v" + health.getVersion() + " (DB: " + health.getDatabase() + ")");
                } else {
                    showOfflineState("Server returned HTTP " + response.code());
                }
            }

            @Override
            public void onFailure(Call<HealthResponse> call, Throwable t) {
                // If 10.0.2.2 timed out and we haven't tried 127.0.0.1 (adb reverse), try it now
                if (!mHasAttemptedFallback && ApiClient.EMULATOR_NAT_URL.equals(ApiClient.getBaseUrl())) {
                    mHasAttemptedFallback = true;
                    ApiClient.setBaseUrl(ApiClient.ADB_REVERSE_URL);
                    updateUrlDisplay();
                    checkBackendHealth();
                    return;
                }

                mProgressConnection.setVisibility(View.GONE);
                mTextStatusBadge.setVisibility(View.VISIBLE);
                showOfflineState("Cannot reach backend: " + t.getLocalizedMessage() +
                        "\nEnsure backend is running (uvicorn on port 8000).");
            }
        });
    }

    private void showOfflineState(String details) {
        mTextStatusBadge.setText("OFFLINE");
        mTextStatusBadge.getBackground().setTint(Color.parseColor("#EF4444")); // Red
        mTextConnectionDetails.setText(details);
        mBtnRetryConnection.setVisibility(View.VISIBLE);
    }

    private void showConfigureUrlDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("Configure Backend URL");

        final EditText input = new EditText(this);
        input.setText(ApiClient.getBaseUrl());
        input.setHint("http://10.0.2.2:8000/");
        builder.setView(input);

        builder.setPositiveButton("Save", (dialog, which) -> {
            String url = input.getText().toString().trim();
            if (!url.isEmpty()) {
                mHasAttemptedFallback = true;
                ApiClient.setBaseUrl(url);
                updateUrlDisplay();
                checkBackendHealth();
                Toast.makeText(this, "Base URL updated", Toast.LENGTH_SHORT).show();
            }
        });
        builder.setNeutralButton("Use 10.0.2.2", (dialog, which) -> {
            mHasAttemptedFallback = true;
            ApiClient.setBaseUrl(ApiClient.EMULATOR_NAT_URL);
            updateUrlDisplay();
            checkBackendHealth();
        });
        builder.setNegativeButton("Cancel", (dialog, which) -> dialog.cancel());
        builder.show();
    }
}