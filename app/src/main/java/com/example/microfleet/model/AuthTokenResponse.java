package com.example.microfleet.model;

import com.google.gson.annotations.SerializedName;

public class AuthTokenResponse {
    @SerializedName("access_token")
    private String accessToken;

    @SerializedName("token_type")
    private String tokenType;

    @SerializedName("user")
    private UserDto user;

    public String getAccessToken() { return accessToken; }
    public String getTokenType() { return tokenType; }
    public UserDto getUser() { return user; }
}
