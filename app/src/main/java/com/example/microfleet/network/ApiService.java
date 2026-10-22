package com.example.microfleet.network;

import com.example.microfleet.model.CreateOrderRequest;
import com.example.microfleet.model.HealthResponse;
import com.example.microfleet.model.MerchantDto;
import com.example.microfleet.model.OrderDto;

import java.util.List;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.POST;
import retrofit2.http.Query;

public interface ApiService {

    @GET("health")
    Call<HealthResponse> getHealth();

    @GET("api/v1/merchants")
    Call<List<MerchantDto>> getMerchants(@Query("active_only") Boolean activeOnly);

    @POST("api/v1/orders")
    Call<OrderDto> createOrder(@Body CreateOrderRequest request);

    @GET("api/v1/orders")
    Call<List<OrderDto>> getOrders(@Query("status") String status);
}
