package com.example.microfleet;

import android.content.Intent;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.example.microfleet.model.AuthTokenResponse;
import com.example.microfleet.model.LoginRequest;
import com.example.microfleet.model.RegisterRequest;
import com.example.microfleet.model.UserDto;
import com.example.microfleet.network.ApiClient;
import com.example.microfleet.network.ApiService;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.textfield.TextInputEditText;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class LoginActivity extends AppCompatActivity {

    private static final int REQUEST_RIDER_PICKER = 2045;

    private TextInputEditText mEditEmail;
    private TextInputEditText mEditPassword;
    private MaterialButton mButtonLogin;
    private MaterialButton mButtonRegister;
    private MaterialButton mButtonDevMerchant;
    private MaterialButton mButtonDevDispatcher;
    private MaterialButton mButtonDevRider;
    private ProgressBar mProgressBar;
    private TextView mTextError;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_login);

        mEditEmail = findViewById(R.id.edit_email);
        mEditPassword = findViewById(R.id.edit_password);
        mButtonLogin = findViewById(R.id.button_login);
        mButtonRegister = findViewById(R.id.button_register);
        mButtonDevMerchant = findViewById(R.id.button_dev_merchant);
        mButtonDevDispatcher = findViewById(R.id.button_dev_dispatcher);
        mButtonDevRider = findViewById(R.id.button_dev_rider);
        mProgressBar = findViewById(R.id.progress_bar);
        mTextError = findViewById(R.id.text_error);

        mButtonLogin.setOnClickListener(v -> performLogin(
                mEditEmail.getText() != null ? mEditEmail.getText().toString().trim() : "",
                mEditPassword.getText() != null ? mEditPassword.getText().toString().trim() : ""
        ));

        mButtonRegister.setOnClickListener(v -> performRegister(
                mEditEmail.getText() != null ? mEditEmail.getText().toString().trim() : "",
                mEditPassword.getText() != null ? mEditPassword.getText().toString().trim() : ""
        ));

        // Quick development logins
        mButtonDevMerchant.setOnClickListener(v -> performLogin("merchant@microfleet.dev", "password123"));
        mButtonDevDispatcher.setOnClickListener(v -> performLogin("dispatcher@microfleet.dev", "password123"));
        mButtonDevRider.setOnClickListener(v -> {
            Intent intent = new Intent(LoginActivity.this, RiderFleetActivity.class);
            intent.putExtra(RiderFleetActivity.EXTRA_SIGN_IN_AS_SELECTED_RIDER, true);
            startActivityForResult(intent, REQUEST_RIDER_PICKER);
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_RIDER_PICKER && resultCode == RESULT_OK) {
            finish();
        }
    }

    private void showLoading(boolean loading) {
        mProgressBar.setVisibility(loading ? View.VISIBLE : View.GONE);
        mButtonLogin.setEnabled(!loading);
        mButtonRegister.setEnabled(!loading);
        mButtonDevMerchant.setEnabled(!loading);
        mButtonDevDispatcher.setEnabled(!loading);
        mButtonDevRider.setEnabled(!loading);
        if (loading) {
            mTextError.setVisibility(View.GONE);
        }
    }

    private void showError(String message) {
        mTextError.setText(message);
        mTextError.setVisibility(View.VISIBLE);
    }

    private void performLogin(String email, String password) {
        if (TextUtils.isEmpty(email) || TextUtils.isEmpty(password)) {
            showError("Please enter both email and password.");
            return;
        }

        showLoading(true);
        ApiService api = ApiClient.getApiService();
        api.login(new LoginRequest(email, password)).enqueue(new Callback<AuthTokenResponse>() {
            @Override
            public void onResponse(Call<AuthTokenResponse> call, Response<AuthTokenResponse> response) {
                showLoading(false);
                if (response.isSuccessful() && response.body() != null) {
                    AuthTokenResponse tokenResp = response.body();
                    UserDto user = tokenResp.getUser();
                    ApiClient.setSession(tokenResp.getAccessToken(), user != null ? user.getEmail() : email, user);
                    navigateForUser(user);
                } else {
                    showError("Authentication failed: " + (response.code() == 401 ? "Invalid credentials" : response.message()));
                }
            }

            @Override
            public void onFailure(Call<AuthTokenResponse> call, Throwable t) {
                showLoading(false);
                showError("Network error: " + t.getMessage());
            }
        });
    }

    private void performRegister(String email, String password) {
        if (TextUtils.isEmpty(email) || TextUtils.isEmpty(password)) {
            showError("Please enter email and password for registration.");
            return;
        }

        showLoading(true);
        // Default self-registration role: MERCHANT
        RegisterRequest req = new RegisterRequest(email, password, "MERCHANT");
        req.setMerchantDetails("Self-Registered Merchant", "Mumbai Commercial District", 19.0596, 72.8295);

        ApiService api = ApiClient.getApiService();
        api.register(req).enqueue(new Callback<AuthTokenResponse>() {
            @Override
            public void onResponse(Call<AuthTokenResponse> call, Response<AuthTokenResponse> response) {
                showLoading(false);
                if (response.isSuccessful() && response.body() != null) {
                    AuthTokenResponse tokenResp = response.body();
                    UserDto user = tokenResp.getUser();
                    ApiClient.setSession(tokenResp.getAccessToken(), user != null ? user.getEmail() : email, user);
                    Toast.makeText(LoginActivity.this, "Registered successfully!", Toast.LENGTH_SHORT).show();
                    navigateForUser(user);
                } else {
                    showError("Registration failed: " + response.message());
                }
            }

            @Override
            public void onFailure(Call<AuthTokenResponse> call, Throwable t) {
                showLoading(false);
                showError("Network error: " + t.getMessage());
            }
        });
    }

    private void navigateForUser(UserDto user) {
        if (user == null) {
            showError("Unable to load authorized user profile.");
            return;
        }

        String role = user.getRole();
        Intent intent;
        if ("DISPATCHER".equalsIgnoreCase(role) || "ADMIN".equalsIgnoreCase(role)) {
            intent = new Intent(this, DispatcherActivity.class);
        } else if ("RIDER".equalsIgnoreCase(role)) {
            intent = new Intent(this, RiderActivity.class);
        } else { // MERCHANT
            intent = new Intent(this, MainActivity.class);
        }
        startActivity(intent);
        finish();
    }
}
