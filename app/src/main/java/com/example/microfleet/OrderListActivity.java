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

import com.example.microfleet.model.OrderDto;
import com.example.microfleet.network.ApiClient;

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

    private OrderAdapter mAdapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
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
                    }
                } else {
                    showErrorState("Server error: HTTP " + response.code());
                }
            }

            @Override
            public void onFailure(Call<List<OrderDto>> call, Throwable t) {
                mProgressOrders.setVisibility(View.GONE);
                showErrorState("Cannot load orders: " + t.getLocalizedMessage() +
                        "\nBackend at " + ApiClient.getBaseUrl() + " is unreachable.");
            }
        });
    }

    private void showErrorState(String message) {
        mContainerError.setVisibility(View.VISIBLE);
        mTextErrorMessage.setText(message);
        mTextOrdersCount.setText("Orders (Error)");
    }
}
