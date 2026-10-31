package com.example.microfleet.map;

import org.osmdroid.util.GeoPoint;

import java.util.List;

/** Convenience methods for the tile-free schematic map used by the demo app. */
public final class MapHelper {

    public static final GeoPoint MUMBAI_CENTER = new GeoPoint(19.0550, 72.8350);

    private MapHelper() { }

    public static void configureMapView(SchematicMapView map, GeoPoint center, double zoom) {
        map.setMapView(center, zoom);
    }

    public static void clearOverlays(SchematicMapView map) {
        map.clearOverlays();
    }

    public static void addMarker(SchematicMapView map, double lat, double lon, String title, String snippet) {
        map.addMarker(lat, lon, title, snippet);
    }

    public static void drawRoutePolyline(SchematicMapView map, List<List<Double>> coordinates, int color, float width) {
        map.addRoute(coordinates, color, width);
    }

    public static void zoomToPoints(SchematicMapView map, List<GeoPoint> points) {
        map.zoomToPoints(points);
    }
}
