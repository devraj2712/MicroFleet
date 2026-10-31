package com.example.microfleet.map;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

import org.osmdroid.util.GeoPoint;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** A tile-free, stylized Mumbai map for the simulated routes in MicroFleet. */
public class SchematicMapView extends View {

    public interface OnMapTapListener {
        void onMapTap(double latitude, double longitude);
    }

    private static final int BACKGROUND = Color.rgb(12, 10, 18);
    private static final int ROAD_SHADOW = Color.rgb(30, 25, 42);
    private static final int ROAD = Color.rgb(55, 45, 75);
    private static final int TEXT = Color.rgb(189, 185, 211);
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Map<String, MapMarker> markers = new LinkedHashMap<>();
    private final List<MapRoute> routes = new ArrayList<>();
    private final ScaleGestureDetector scaleDetector;

    private double centerLat = 19.0550;
    private double centerLon = 72.8350;
    private double spanLat = 0.20;
    private double spanLon = 0.25;
    private double resetCenterLat = centerLat;
    private double resetCenterLon = centerLon;
    private double resetSpanLat = spanLat;
    private double resetSpanLon = spanLon;
    private OnMapTapListener tapListener;
    private float downX;
    private float downY;
    private float lastX;
    private float lastY;
    private boolean moved;
    private int downControl;
    private boolean viewConfigured;
    private boolean hasFitPoints;

    private static final int CONTROL_NONE = 0;
    private static final int CONTROL_ZOOM_IN = 1;
    private static final int CONTROL_ZOOM_OUT = 2;
    private static final int CONTROL_RESET = 3;

    public SchematicMapView(Context context) {
        this(context, null);
    }

    public SchematicMapView(Context context, AttributeSet attrs) {
        this(context, attrs, 0);
    }

    public SchematicMapView(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        scaleDetector = new ScaleGestureDetector(context, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override
            public boolean onScale(ScaleGestureDetector detector) {
                double factor = Math.max(0.75, Math.min(1.35, detector.getScaleFactor()));
                spanLat = clamp(spanLat / factor, 0.025, 1.5);
                spanLon = clamp(spanLon / factor, 0.025, 1.8);
                invalidate();
                return true;
            }
        });
        setContentDescription("Schematic map. Drag to move, pinch to zoom, or use the plus, minus, and reset map controls.");
    }

    public void setOnMapTapListener(OnMapTapListener listener) {
        tapListener = listener;
    }

    public void setMapView(GeoPoint center, double zoom) {
        viewConfigured = true;
        hasFitPoints = false;
        if (center != null) {
            centerLat = center.getLatitude();
            centerLon = center.getLongitude();
        }
        double scale = Math.pow(2.0, 12.0 - zoom);
        spanLat = clamp(0.20 * scale, 0.035, 1.5);
        spanLon = clamp(spanLat * aspectRatio(), 0.05, 1.8);
        saveResetViewport();
        invalidate();
    }

    public void centerOn(GeoPoint point) {
        if (point == null) return;
        centerLat = point.getLatitude();
        centerLon = point.getLongitude();
        invalidate();
    }

    public void clearOverlays() {
        markers.clear();
        routes.clear();
        invalidate();
    }

    public void addMarker(double latitude, double longitude, String title, String snippet) {
        String key = String.format(Locale.US, "%s@%.5f,%.5f", title == null ? "stop" : title, latitude, longitude);
        markers.put(key, new MapMarker(latitude, longitude, title, snippet, markerColor(title)));
        invalidate();
    }

    public void putMarker(String key, double latitude, double longitude, String title, String snippet, int color) {
        markers.put(key, new MapMarker(latitude, longitude, title, snippet, color));
        invalidate();
    }

    public void addRoute(List<List<Double>> coordinates, int color, float width) {
        if (coordinates == null || coordinates.isEmpty()) return;
        MapRoute route = new MapRoute(color, width);
        for (List<Double> coordinate : coordinates) {
            if (coordinate != null && coordinate.size() >= 2 && coordinate.get(0) != null && coordinate.get(1) != null) {
                route.points.add(new GeoPoint(coordinate.get(0), coordinate.get(1)));
            }
        }
        if (route.points.size() > 1) routes.add(route);
        invalidate();
    }

    public void zoomToPoints(List<GeoPoint> points) {
        if (points == null || points.isEmpty()) return;
        double minLat = Double.MAX_VALUE, maxLat = -Double.MAX_VALUE;
        double minLon = Double.MAX_VALUE, maxLon = -Double.MAX_VALUE;
        for (GeoPoint point : points) {
            if (point == null) continue;
            minLat = Math.min(minLat, point.getLatitude());
            maxLat = Math.max(maxLat, point.getLatitude());
            minLon = Math.min(minLon, point.getLongitude());
            maxLon = Math.max(maxLon, point.getLongitude());
        }
        if (minLat == Double.MAX_VALUE) return;
        hasFitPoints = true;
        centerLat = (minLat + maxLat) / 2.0;
        centerLon = (minLon + maxLon) / 2.0;
        spanLat = Math.max(0.045, (maxLat - minLat) * 1.55 + 0.025);
        spanLon = Math.max(0.055, (maxLon - minLon) * 1.45 + 0.025);
        double aspect = aspectRatio();
        if (spanLon < spanLat * aspect) spanLon = spanLat * aspect;
        else spanLat = spanLon / Math.max(1.0, aspect);
        spanLat = clamp(spanLat, 0.035, 1.5);
        spanLon = clamp(spanLon, 0.05, 1.8);
        saveResetViewport();
        invalidate();
    }

    private void saveResetViewport() {
        resetCenterLat = centerLat;
        resetCenterLon = centerLon;
        resetSpanLat = spanLat;
        resetSpanLon = spanLon;
    }

    private void zoomBy(double factor) {
        spanLat = clamp(spanLat * factor, 0.025, 1.5);
        spanLon = clamp(spanLon * factor, 0.025, 1.8);
        invalidate();
    }

    private void resetViewport() {
        centerLat = resetCenterLat;
        centerLon = resetCenterLon;
        spanLat = resetSpanLat;
        spanLon = resetSpanLon;
        invalidate();
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        if (width > 0 && height > 0 && viewConfigured && !hasFitPoints
                && (oldWidth == 0 || oldHeight == 0)) {
            spanLon = clamp(spanLat * aspectRatio(), 0.05, 1.8);
            saveResetViewport();
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w = getWidth();
        float h = getHeight();
        if (w <= 0 || h <= 0) return;

        canvas.drawColor(BACKGROUND);
        drawDistrictGlow(canvas, w, h);
        drawSchematicRoads(canvas, w, h);
        drawDistrictLabels(canvas, w, h);
        drawRoutes(canvas);
        drawMarkers(canvas);
        drawMapKey(canvas, w, h);
        drawMapControls(canvas, w);
    }

    private void drawDistrictGlow(Canvas canvas, float w, float h) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.rgb(22, 17, 34));
        canvas.drawOval(new RectF(-w * 0.25f, h * 0.12f, w * 0.58f, h * 0.92f), paint);
        paint.setColor(Color.rgb(17, 17, 29));
        canvas.drawOval(new RectF(w * 0.50f, -h * 0.2f, w * 1.2f, h * 0.62f), paint);
    }

    private void drawSchematicRoads(Canvas canvas, float w, float h) {
        // Curved, deliberately simplified street bands provide map texture without remote tiles.
        for (int i = 0; i < 8; i++) {
            float y = h * (0.08f + i * 0.12f);
            Path road = new Path();
            road.moveTo(-w * 0.08f, y + h * 0.07f);
            road.cubicTo(w * 0.22f, y - h * 0.08f, w * 0.55f, y + h * 0.13f, w * 1.08f, y - h * 0.04f);
            drawRoad(canvas, road, dp(i == 3 ? 2.0f : 0.9f));
        }
        for (int i = 0; i < 8; i++) {
            float x = w * (0.04f + i * 0.14f);
            Path road = new Path();
            road.moveTo(x - w * 0.04f, -h * 0.08f);
            road.cubicTo(x + w * 0.12f, h * 0.28f, x - w * 0.12f, h * 0.68f, x + w * 0.05f, h * 1.08f);
            drawRoad(canvas, road, dp(i == 4 ? 2.0f : 0.9f));
        }
        Path coast = new Path();
        coast.moveTo(w * 0.12f, -h * 0.05f);
        coast.cubicTo(w * 0.26f, h * 0.25f, w * 0.10f, h * 0.55f, w * 0.28f, h * 1.05f);
        paint.setColor(Color.rgb(27, 31, 50));
        paint.setStrokeWidth(dp(3f));
        paint.setStyle(Paint.Style.STROKE);
        canvas.drawPath(coast, paint);
        paint.setColor(Color.rgb(55, 60, 91));
        paint.setStrokeWidth(dp(0.7f));
        canvas.drawPath(coast, paint);
        paint.setStyle(Paint.Style.FILL);
    }

    private void drawRoad(Canvas canvas, Path path, float width) {
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeCap(Paint.Cap.ROUND);
        paint.setStrokeJoin(Paint.Join.ROUND);
        paint.setColor(ROAD_SHADOW);
        paint.setStrokeWidth(width + 3f);
        canvas.drawPath(path, paint);
        paint.setColor(ROAD);
        paint.setStrokeWidth(width);
        canvas.drawPath(path, paint);
        paint.setStyle(Paint.Style.FILL);
    }

    private void drawDistrictLabels(Canvas canvas, float w, float h) {
        String[] names = {"ANDHERI", "BANDRA", "DADAR", "LOWER PAREL", "WORLI"};
        double[][] coords = {{19.1136,72.8697},{19.0550,72.8350},{19.0178,72.8478},{18.9950,72.8300},{19.0150,72.8150}};
        paint.setTextSize(Math.max(9f, getResources().getDisplayMetrics().scaledDensity * 9f));
        paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL));
        paint.setColor(Color.rgb(116, 108, 143));
        for (int i = 0; i < names.length; i++) {
            float[] p = project(coords[i][0], coords[i][1], w, h);
            if (inside(p[0], p[1], w, h, 30f)) canvas.drawText(names[i], p[0] + 8f, p[1] - 14f, paint);
        }
    }

    private void drawRoutes(Canvas canvas) {
        for (MapRoute route : routes) {
            Path path = new Path();
            boolean first = true;
            for (GeoPoint point : route.points) {
                float[] p = project(point.getLatitude(), point.getLongitude(), getWidth(), getHeight());
                if (first) { path.moveTo(p[0], p[1]); first = false; }
                else path.lineTo(p[0], p[1]);
            }
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
            paint.setColor(Color.argb(75, Color.red(route.color), Color.green(route.color), Color.blue(route.color)));
            paint.setStrokeWidth(dp(route.width + 6f));
            canvas.drawPath(path, paint);
            paint.setColor(route.color);
            paint.setStrokeWidth(dp(route.width));
            canvas.drawPath(path, paint);
            paint.setStyle(Paint.Style.FILL);
        }
    }

    private void drawMarkers(Canvas canvas) {
        float w = getWidth(), h = getHeight();
        paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL));
        for (MapMarker marker : markers.values()) {
            float[] p = project(marker.latitude, marker.longitude, w, h);
            if (!inside(p[0], p[1], w, h, dp(22f))) continue;
            paint.setColor(Color.argb(65, Color.red(marker.color), Color.green(marker.color), Color.blue(marker.color)));
            canvas.drawCircle(p[0], p[1], dp(13f), paint);
            paint.setColor(Color.rgb(22, 19, 31));
            canvas.drawCircle(p[0], p[1], dp(8.5f), paint);
            paint.setColor(marker.color);
            canvas.drawCircle(p[0], p[1], dp(5.5f), paint);
            paint.setColor(Color.WHITE);
            canvas.drawCircle(p[0], p[1], dp(1.8f), paint);

            String label = shortLabel(marker.title);
            paint.setTextSize(10f * getResources().getDisplayMetrics().scaledDensity);
            float textWidth = paint.measureText(label);
            float left = Math.min(w - textWidth - dp(14f), p[0] + dp(11f));
            float top = Math.max(dp(8f), p[1] - dp(28f));
            paint.setColor(Color.argb(225, 25, 21, 36));
            canvas.drawRoundRect(new RectF(left - dp(5f), top - dp(14f), left + textWidth + dp(5f), top + dp(4f)), dp(6f), dp(6f), paint);
            paint.setColor(marker.color);
            canvas.drawText(label, left, top, paint);
        }
    }

    private void drawMapKey(Canvas canvas, float w, float h) {
        paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL));
        paint.setTextSize(9f * getResources().getDisplayMetrics().scaledDensity);
        String text = "SIMULATED STREETS  •  © OPENSTREETMAP CONTRIBUTORS  •  NOT TO SCALE";
        float width = paint.measureText(text);
        paint.setColor(Color.argb(220, 20, 17, 29));
        canvas.drawRoundRect(new RectF(dp(9f), h - dp(27f), Math.min(w - dp(8f), width + dp(25f)), h - dp(9f)), dp(7f), dp(7f), paint);
        paint.setColor(TEXT);
        canvas.drawText(text, dp(16f), h - dp(15f), paint);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        scaleDetector.onTouchEvent(event);
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(true);
                downX = lastX = event.getX();
                downY = lastY = event.getY();
                downControl = controlAt(downX, downY);
                moved = false;
                return true;
            case MotionEvent.ACTION_MOVE:
                if (event.getPointerCount() > 1) {
                    moved = true;
                    lastX = event.getX(0);
                    lastY = event.getY(0);
                } else {
                    float dx = event.getX() - lastX;
                    float dy = event.getY() - lastY;
                    if (Math.abs(event.getX() - downX) + Math.abs(event.getY() - downY) > dp(5f)) moved = true;
                    if (moved && downControl == CONTROL_NONE) {
                        centerLon -= dx / Math.max(1f, getWidth()) * spanLon;
                        centerLat += dy / Math.max(1f, getHeight()) * spanLat;
                        invalidate();
                    }
                    lastX = event.getX();
                    lastY = event.getY();
                }
                return true;
            case MotionEvent.ACTION_UP:
                if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
                int releasedControl = controlAt(event.getX(), event.getY());
                if (!moved && downControl != CONTROL_NONE && downControl == releasedControl) {
                    if (downControl == CONTROL_ZOOM_IN) zoomBy(0.75);
                    else if (downControl == CONTROL_ZOOM_OUT) zoomBy(1.33);
                    else if (downControl == CONTROL_RESET) resetViewport();
                    performClick();
                } else if (!moved && downControl == CONTROL_NONE && !scaleDetector.isInProgress()) {
                    if (tapListener != null) {
                        GeoPoint point = unproject(event.getX(), event.getY());
                        tapListener.onMapTap(point.getLatitude(), point.getLongitude());
                    }
                    performClick();
                }
                return true;
            case MotionEvent.ACTION_CANCEL:
                if (getParent() != null) getParent().requestDisallowInterceptTouchEvent(false);
                return true;
            default:
                return true;
        }
    }

    @Override
    public boolean performClick() {
        super.performClick();
        return true;
    }

    private void drawMapControls(Canvas canvas, float width) {
        float size = dp(38f);
        float gap = dp(6f);
        float right = width - dp(12f);
        float left = right - size;
        float top = dp(12f);
        int[] controlIds = {CONTROL_ZOOM_IN, CONTROL_ZOOM_OUT, CONTROL_RESET};
        String[] symbols = {"+", "−", "↺"};
        for (int i = 0; i < controlIds.length; i++) {
            float controlTop = top + i * (size + gap);
            paint.setColor(Color.argb(235, 25, 21, 36));
            canvas.drawRoundRect(new RectF(left, controlTop, right, controlTop + size), dp(11f), dp(11f), paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(1f));
            paint.setColor(Color.rgb(83, 68, 116));
            canvas.drawRoundRect(new RectF(left, controlTop, right, controlTop + size), dp(11f), dp(11f), paint);
            paint.setStyle(Paint.Style.FILL);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTextSize(i == 2 ? dp(21f) : dp(24f));
            paint.setTypeface(android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL));
            paint.setColor(Color.rgb(220, 207, 255));
            canvas.drawText(symbols[i], left + size / 2f, controlTop + size / 2f + dp(8f), paint);
        }
        paint.setTextAlign(Paint.Align.LEFT);
    }

    private int controlAt(float x, float y) {
        float size = dp(38f);
        float gap = dp(6f);
        float left = getWidth() - dp(12f) - size;
        float top = dp(12f);
        if (x < left || x > left + size) return CONTROL_NONE;
        for (int i = 0; i < 3; i++) {
            float controlTop = top + i * (size + gap);
            if (y >= controlTop && y <= controlTop + size) return i + 1;
        }
        return CONTROL_NONE;
    }

    private float[] project(double lat, double lon, float w, float h) {
        float x = (float) ((lon - (centerLon - spanLon / 2.0)) / spanLon * w);
        float y = (float) (((centerLat + spanLat / 2.0) - lat) / spanLat * h);
        return new float[]{x, y};
    }

    private GeoPoint unproject(float x, float y) {
        double lon = centerLon - spanLon / 2.0 + x / Math.max(1f, getWidth()) * spanLon;
        double lat = centerLat + spanLat / 2.0 - y / Math.max(1f, getHeight()) * spanLat;
        return new GeoPoint(lat, lon);
    }

    private double aspectRatio() {
        float h = Math.max(1f, getHeight()), w = Math.max(1f, getWidth());
        return Math.max(1.0, w / h);
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }

    private static boolean inside(float x, float y, float w, float h, float margin) {
        return x >= -margin && x <= w + margin && y >= -margin && y <= h + margin;
    }

    private static double clamp(double value, double min, double max) {
        return Math.max(min, Math.min(max, value));
    }

    private static int markerColor(String title) {
        String lower = title == null ? "" : title.toLowerCase(Locale.US);
        if (lower.contains("rider")) return Color.rgb(110, 231, 168);
        if (lower.contains("pickup") || lower.contains("merchant")) return Color.rgb(183, 155, 255);
        if (lower.contains("delivery") || lower.contains("destination")) return Color.rgb(251, 113, 133);
        return Color.rgb(251, 191, 36);
    }

    private static String shortLabel(String title) {
        if (title == null) return "STOP";
        String lower = title.toLowerCase(Locale.US);
        if (lower.contains("rider")) {
            int at = lower.indexOf("rider") + 5;
            while (at < title.length() && !Character.isDigit(title.charAt(at))) at++;
            return at < title.length() ? "R" + title.charAt(at) : "RIDER";
        }
        if (lower.contains("pickup") || lower.contains("merchant")) return "PICKUP";
        if (lower.contains("delivery") || lower.contains("destination")) return "DROP";
        int at = lower.indexOf("stop");
        if (at >= 0) {
            at += 4;
            while (at < title.length() && !Character.isDigit(title.charAt(at))) at++;
            if (at < title.length()) return "S" + title.charAt(at);
        }
        return "STOP";
    }

    private static final class MapMarker {
        final double latitude, longitude;
        final String title, snippet;
        final int color;
        MapMarker(double latitude, double longitude, String title, String snippet, int color) {
            this.latitude = latitude; this.longitude = longitude; this.title = title; this.snippet = snippet; this.color = color;
        }
    }

    private static final class MapRoute {
        final int color;
        final float width;
        final List<GeoPoint> points = new ArrayList<>();
        MapRoute(int color, float width) { this.color = color; this.width = Math.max(3f, width / 2.5f); }
    }
}
