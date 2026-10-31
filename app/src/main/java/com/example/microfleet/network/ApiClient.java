package com.example.microfleet.network;

import com.example.microfleet.model.UserDto;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class ApiClient {

    // Direct loopback via adb reverse tcp:8000 tcp:8000 (fastest and most reliable on Windows)
    public static final String ADB_REVERSE_URL = "http://127.0.0.1:8000/";
    // Standard QEMU Android emulator NAT loopback alias
    public static final String EMULATOR_NAT_URL = "http://10.0.2.2:8000/";

    private static String sBaseUrl = ADB_REVERSE_URL;
    private static ApiService sApiService;
    private static Retrofit sRetrofit;

    private static String sAuthToken = null;
    private static String sDevUserEmail = null;
    private static UserDto sCurrentUser = null;

    public static synchronized void setBaseUrl(String newUrl) {
        if (newUrl != null && !newUrl.endsWith("/")) {
            newUrl += "/";
        }
        sBaseUrl = newUrl;
        sApiService = null; // Recreate on next request
        sRetrofit = null;
    }

    public static String getBaseUrl() {
        return sBaseUrl;
    }

    public static synchronized void setSession(String token, String devEmail, UserDto user) {
        sAuthToken = token;
        sDevUserEmail = devEmail;
        sCurrentUser = user;
        sApiService = null; // Recreate with updated headers
    }

    public static synchronized void clearSession() {
        sAuthToken = null;
        sDevUserEmail = null;
        sCurrentUser = null;
        sApiService = null;
    }

    public static UserDto getCurrentUser() {
        return sCurrentUser;
    }

    public static String getDevUserEmail() {
        return sDevUserEmail;
    }

    public static synchronized ApiService getApiService() {
        if (sApiService == null) {
            HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
            logging.setLevel(HttpLoggingInterceptor.Level.BODY);

            Interceptor authInterceptor = new Interceptor() {
                @Override
                public Response intercept(Chain chain) throws IOException {
                    Request original = chain.request();
                    Request.Builder builder = original.newBuilder();

                    if (sAuthToken != null && !sAuthToken.isEmpty()) {
                        builder.header("Authorization", "Bearer " + sAuthToken);
                    }
                    if (sDevUserEmail != null && !sDevUserEmail.isEmpty()) {
                        builder.header("X-Dev-User-Email", sDevUserEmail);
                    }
                    return chain.proceed(builder.build());
                }
            };

            OkHttpClient okHttpClient = new OkHttpClient.Builder()
                    .connectTimeout(15, TimeUnit.SECONDS)
                    .readTimeout(60, TimeUnit.SECONDS) // GA+ACO+RL preview can take 5-15s
                    .writeTimeout(30, TimeUnit.SECONDS)
                    .addInterceptor(authInterceptor)
                    .addInterceptor(logging)
                    .build();

            sRetrofit = new Retrofit.Builder()
                    .baseUrl(sBaseUrl)
                    .client(okHttpClient)
                    .addConverterFactory(GsonConverterFactory.create())
                    .build();

            sApiService = sRetrofit.create(ApiService.class);
        }
        return sApiService;
    }
}
