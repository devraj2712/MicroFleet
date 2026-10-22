package com.example.microfleet;

import android.graphics.Color;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.example.microfleet.model.OrderDto;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public class OrderAdapter extends RecyclerView.Adapter<OrderAdapter.OrderViewHolder> {

    private List<OrderDto> mOrders = new ArrayList<>();

    public void setOrders(List<OrderDto> orders) {
        mOrders = orders != null ? orders : new ArrayList<>();
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public OrderViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_order, parent, false);
        return new OrderViewHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull OrderViewHolder holder, int position) {
        OrderDto order = mOrders.get(position);
        holder.textOrderId.setText(order.getId());
        holder.textOrderStatus.setText(order.getStatus());

        // Status badge colors
        int badgeColor = Color.parseColor("#64748B"); // Default grey
        if ("PENDING".equalsIgnoreCase(order.getStatus())) {
            badgeColor = Color.parseColor("#D97706"); // Amber
        } else if ("BATCHED".equalsIgnoreCase(order.getStatus())) {
            badgeColor = Color.parseColor("#2563EB"); // Blue
        } else if ("DISPATCHED".equalsIgnoreCase(order.getStatus())) {
            badgeColor = Color.parseColor("#7C3AED"); // Purple
        } else if ("DELIVERED".equalsIgnoreCase(order.getStatus())) {
            badgeColor = Color.parseColor("#16A34A"); // Green
        } else if ("CANCELLED".equalsIgnoreCase(order.getStatus())) {
            badgeColor = Color.parseColor("#DC2626"); // Red
        }
        holder.textOrderStatus.getBackground().setTint(badgeColor);

        holder.textOrderMerchant.setText("Merchant: " + order.getMerchantId());
        holder.textOrderDestination.setText(String.format(Locale.US,
                "Destination: %.4f, %.4f",
                order.getDeliveryLatitude(),
                order.getDeliveryLongitude()));

        String deadlineStr = order.getDeliveryDeadline();
        if (deadlineStr != null && deadlineStr.length() > 16) {
            deadlineStr = deadlineStr.substring(0, 16).replace("T", " ") + " UTC";
        }
        holder.textOrderDeadline.setText("Deadline: " + deadlineStr);

        holder.textOrderSpecs.setText(String.format(Locale.US,
                "Type: %s | %.1f kg | Pkg: %d | Priority: %s",
                order.getPackageType(),
                order.getWeightKg(),
                order.getPackageCount(),
                order.getCustomerPriority()));
    }

    @Override
    public int getItemCount() {
        return mOrders.size();
    }

    static class OrderViewHolder extends RecyclerView.ViewHolder {
        TextView textOrderId;
        TextView textOrderStatus;
        TextView textOrderMerchant;
        TextView textOrderDestination;
        TextView textOrderDeadline;
        TextView textOrderSpecs;

        public OrderViewHolder(@NonNull View itemView) {
            super(itemView);
            textOrderId = itemView.findViewById(R.id.text_order_id);
            textOrderStatus = itemView.findViewById(R.id.text_order_status);
            textOrderMerchant = itemView.findViewById(R.id.text_order_merchant);
            textOrderDestination = itemView.findViewById(R.id.text_order_destination);
            textOrderDeadline = itemView.findViewById(R.id.text_order_deadline);
            textOrderSpecs = itemView.findViewById(R.id.text_order_specs);
        }
    }
}
