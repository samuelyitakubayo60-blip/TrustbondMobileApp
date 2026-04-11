import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../config/theme.dart';
import '../services/hotspot_service.dart';

class HotspotMarker {
  static Marker createMarker(Hotspot hotspot, {Function()? onTap}) {
    print('🔍 DEBUG: Creating marker for hotspot ${hotspot.hotspotId}');
    print('🔍 DEBUG: Location: ${hotspot.centerLat}, ${hotspot.centerLong}');
    print('🔍 DEBUG: Risk: ${hotspot.riskLevel}');
    
    return Marker(
      point: LatLng(hotspot.centerLat, hotspot.centerLong),
      width: 80, // Increased size for visibility
      height: 80, // Increased size for visibility
      child: GestureDetector(
        onTap: () {
          print('🔍 DEBUG: Hotspot ${hotspot.hotspotId} tapped!');
          onTap?.call();
        },
        child: Stack(
          alignment: Alignment.center,
          children: [
            // Outer glow - very visible
            Container(
              width: 60,
              height: 60,
              decoration: BoxDecoration(
                color: _getHotspotColor(hotspot.riskLevel).withValues(alpha: 0.4),
                shape: BoxShape.circle,
                border: Border.all(
                  color: _getHotspotColor(hotspot.riskLevel),
                  width: 3,
                ),
              ),
            ),
            
            // Middle circle - main visible part
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: _getHotspotColor(hotspot.riskLevel),
                shape: BoxShape.circle,
                border: Border.all(
                  color: Colors.white,
                  width: 3,
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.3),
                    blurRadius: 8,
                    spreadRadius: 2,
                  ),
                ],
              ),
            ),
            
            // Inner circle with text
            Container(
              width: 25,
              height: 25,
              decoration: BoxDecoration(
                color: Colors.white,
                shape: BoxShape.circle,
                border: Border.all(
                  color: _getHotspotColor(hotspot.riskLevel),
                  width: 2,
                ),
              ),
              child: Center(
                child: Text(
                  hotspot.incidentCount.toString(),
                  style: TextStyle(
                    color: _getHotspotColor(hotspot.riskLevel),
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
            
            // Debug text overlay
            Positioned(
              top: -5,
              left: -5,
              child: Container(
                padding: const EdgeInsets.all(2),
                decoration: BoxDecoration(
                  color: Colors.red,
                  borderRadius: BorderRadius.circular(3),
                ),
                child: const Text(
                  'DEBUG',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 8,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
  
  static Color _getHotspotColor(String riskLevel) {
    switch (riskLevel.toLowerCase()) {
      case 'high':
        return Colors.red;
      case 'medium':
        return Colors.orange;
      case 'low':
        return Colors.green;
      default:
        return Colors.purple; // Changed to purple for visibility
    }
  }
}

// Simple test widget to verify hotspot rendering
class HotspotTestWidget extends StatelessWidget {
  final List<Hotspot> hotspots;
  
  const HotspotTestWidget({super.key, required this.hotspots});
  
  @override
  Widget build(BuildContext context) {
    print('🔍 DEBUG: HotspotTestWidget building with ${hotspots.length} hotspots');
    
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(8),
          color: Colors.yellow,
          child: Text(
            'HOTSPOT TEST: ${hotspots.length} hotspots loaded',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.bold,
              color: Colors.black,
            ),
          ),
        ),
        Expanded(
          child: hotspots.isEmpty
              ? const Center(
                  child: Text(
                    'No hotspots to display',
                    style: TextStyle(fontSize: 18, color: Colors.red),
                  ),
                )
              : ListView.builder(
                  itemCount: hotspots.length,
                  itemBuilder: (context, index) {
                    final hotspot = hotspots[index];
                    return Container(
                      margin: const EdgeInsets.all(8),
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: Colors.blue.shade100,
                        border: Border.all(color: Colors.blue, width: 2),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Hotspot ${index + 1}',
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          Text('ID: ${hotspot.hotspotId}'),
                          Text('Location: ${hotspot.centerLat}, ${hotspot.centerLong}'),
                          Text('Risk: ${hotspot.riskLevel}'),
                          Text('Incidents: ${hotspot.incidentCount}'),
                          Container(
                            width: 30,
                            height: 30,
                            decoration: BoxDecoration(
                              color: HotspotMarker._getHotspotColor(hotspot.riskLevel),
                              shape: BoxShape.circle,
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}
