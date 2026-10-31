package com.example.microfleet.network;

import com.example.microfleet.model.AssignedRouteDto;
import com.example.microfleet.model.AuthTokenResponse;
import com.example.microfleet.model.CreateOrderRequest;
import com.example.microfleet.model.DispatchCommitRequest;
import com.example.microfleet.model.DispatchCommitResponse;
import com.example.microfleet.model.DispatchPreviewResponse;
import com.example.microfleet.model.HealthResponse;
import com.example.microfleet.model.LoginRequest;
import com.example.microfleet.model.MerchantDto;
import com.example.microfleet.model.OrderDto;
import com.example.microfleet.model.RegisterRequest;
import com.example.microfleet.model.UpdateOrderStatusRequest;
import com.example.microfleet.model.UserDto;

import java.util.List;
import java.util.Map;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.PATCH;
import retrofit2.http.POST;
import retrofit2.http.Path;
import retrofit2.http.Query;

public interface ApiService {

    @GET("health")
    Call<HealthResponse> getHealth();

    // Authentication
    @POST("api/v1/auth/register")
    Call<AuthTokenResponse> register(@Body RegisterRequest request);

    @POST("api/v1/auth/login")
    Call<AuthTokenResponse> login(@Body LoginRequest request);

    @GET("api/v1/auth/me")
    Call<UserDto> getProfile();

    // Merchants & Orders
    @GET("api/v1/merchants")
    Call<List<MerchantDto>> getMerchants(@Query("active_only") Boolean activeOnly);

    @GET("api/v1/riders")
    Call<List<com.example.microfleet.model.RiderDto>> getRiders(@Query("available_only") Boolean availableOnly);

    @POST("api/v1/orders")
    Call<OrderDto> createOrder(@Body CreateOrderRequest request);

    @GET("api/v1/orders")
    Call<List<OrderDto>> getOrders(@Query("status") String status);

    // Dispatcher optimization preview & commit
    @POST("api/v1/optimization/dispatch/preview")
    Call<DispatchPreviewResponse> getDispatchPreview(@Body Map<String, Object> body);

    @POST("api/v1/optimization/dispatch/commit")
    Call<DispatchCommitResponse> commitDispatchPlan(@Body DispatchCommitRequest request);

    // Rider workflow
    @GET("api/v1/riders/{id}/assigned-routes")
    Call<List<AssignedRouteDto>> getAssignedRoutes(@Path("id") String riderId);

    @POST("api/v1/riders/{id}/routes/{route_id}/start")
    Call<Map<String, Object>> startRoute(@Path("id") String riderId, @Path("route_id") String routeId);

    @PATCH("api/v1/orders/{id}/status")
    Call<OrderDto> updateOrderStatus(@Path("id") String orderId, @Body UpdateOrderStatusRequest request);

    // Development & Demo Reset
    @POST("api/v1/demo/reset")
    Call<Map<String, Object>> resetDemoData();
}
