package com.example.microfleet.network;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
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

    public static synchronized ApiService getApiService() {
        if (sApiService == null) {
            HttpLoggingInterceptor logging = new HttpLoggingInterceptor();
            logging.setLevel(HttpLoggingInterceptor.Level.BODY);

            OkHttpClient okHttpClient = new OkHttpClient.Builder()
                    .connectTimeout(5, TimeUnit.SECONDS)
                    .readTimeout(10, TimeUnit.SECONDS)
                    .writeTimeout(10, TimeUnit.SECONDS)
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
