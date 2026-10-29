package com.example.microfleet.map;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Paint;

import org.osmdroid.config.Configuration;
import org.osmdroid.tileprovider.tilesource.TileSourceFactory;
import org.osmdroid.util.BoundingBox;
import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;
import org.osmdroid.views.overlay.Marker;
import org.osmdroid.views.overlay.Polyline;

import java.util.ArrayList;
import java.util.List;

public class MapHelper {

    public static final GeoPoint MUMBAI_CENTER = new GeoPoint(19.0550, 72.8350); // Bandra center

    public static void initOsmdroid(Context context) {
        Configuration.getInstance().load(context, context.getSharedPreferences("osmdroid_prefs", Context.MODE_PRIVATE));
        Configuration.getInstance().setUserAgentValue(context.getPackageName());
    }

    public static void configureMapView(MapView map, GeoPoint center, double zoom) {
        map.setTileSource(TileSourceFactory.MAPNIK);
        map.setMultiTouchControls(true);
        map.getController().setZoom(zoom);
        map.getController().setCenter(center != null ? center : MUMBAI_CENTER);
    }

    public static Marker addMarker(MapView map, double lat, double lon, String title, String snippet) {
        Marker marker = new Marker(map);
        marker.setPosition(new GeoPoint(lat, lon));
        marker.setTitle(title);
        marker.setSnippet(snippet);
        map.getOverlays().add(marker);
        map.invalidate();
        return marker;
    }

    public static Polyline drawRoutePolyline(MapView map, List<List<Double>> coordinates, int color, float width) {
        if (coordinates == null || coordinates.isEmpty()) {
            return null;
        }

        Polyline polyline = new Polyline(map);
        List<GeoPoint> geoPoints = new ArrayList<>();
        for (List<Double> coord : coordinates) {
            if (coord != null && coord.size() >= 2) {
                geoPoints.add(new GeoPoint(coord.get(0), coord.get(1)));
            }
        }

        if (geoPoints.isEmpty()) {
            return null;
        }

        polyline.setPoints(geoPoints);
        polyline.getOutlinePaint().setColor(color);
        polyline.getOutlinePaint().setStrokeWidth(width);
        polyline.getOutlinePaint().setStrokeCap(Paint.Cap.ROUND);
        polyline.getOutlinePaint().setStrokeJoin(Paint.Join.ROUND);

        map.getOverlays().add(polyline);
        map.invalidate();
        return polyline;
    }

    public static void zoomToPoints(MapView map, List<GeoPoint> points) {
        if (points == null || points.isEmpty()) {
            return;
        }
        if (points.size() == 1) {
            map.getController().setCenter(points.get(0));
            map.getController().setZoom(15.0);
            return;
        }

        double minLat = Double.MAX_VALUE;
        double maxLat = -Double.MAX_VALUE;
        double minLon = Double.MAX_VALUE;
        double maxLon = -Double.MAX_VALUE;

        for (GeoPoint p : points) {
            minLat = Math.min(minLat, p.getLatitude());
            maxLat = Math.max(maxLat, p.getLatitude());
            minLon = Math.min(minLon, p.getLongitude());
            maxLon = Math.max(maxLon, p.getLongitude());
        }

        BoundingBox box = new BoundingBox(maxLat + 0.01, maxLon + 0.01, minLat - 0.01, minLon - 0.01);
        map.zoomToBoundingBox(box, true, 40);
    }
}
