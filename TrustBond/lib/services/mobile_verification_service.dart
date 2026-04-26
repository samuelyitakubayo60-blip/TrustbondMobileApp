import 'dart:io';
import 'package:geolocator/geolocator.dart';
import 'package:image/image.dart' as img;
import 'package:exif/exif.dart';

class MobileVerificationResult {
  final String status; // "passed", "failed", "warning"
  final Map<String, dynamic> details;
  final bool locationConsistencyCheck;
  final bool evidenceSourceValid;
  final bool evidenceTamperingDetected;

  MobileVerificationResult({
    required this.status,
    required this.details,
    required this.locationConsistencyCheck,
    required this.evidenceSourceValid,
    required this.evidenceTamperingDetected,
  });

  Map<String, dynamic> toJson() {
    return {
      'mobile_rule_status': status,
      'mobile_rule_details': details,
      'location_consistency_check': locationConsistencyCheck,
      'evidence_source_valid': evidenceSourceValid,
      'evidence_tampering_detected': evidenceTamperingDetected,
    };
  }
}

class MobileVerificationService {
  static final MobileVerificationService _instance = MobileVerificationService._internal();
  factory MobileVerificationService() => _instance;
  MobileVerificationService._internal();

  /// Perform comprehensive mobile rule-based verification
  Future<MobileVerificationResult> verifyReport({
    required Position reportLocation,
    required List<File> evidenceFiles,
    required List<Map<String, dynamic>> evidenceMetadata,
  }) async {
    final details = <String, dynamic>{};
    bool allChecksPassed = true;
    bool hasWarnings = false;

    // 1. Location consistency checks
    final locationResult = await _checkLocationConsistency(
      reportLocation, 
      evidenceMetadata
    );
    details['location_consistency'] = locationResult;
    if (!locationResult['passed']) {
      allChecksPassed = false;
    }
    if (locationResult['warning'] == true) {
      hasWarnings = true;
    }

    // 2. Evidence source validation
    final sourceResult = await _validateEvidenceSource(evidenceFiles);
    details['evidence_source'] = sourceResult;
    if (!sourceResult['all_valid']) {
      allChecksPassed = false;
    }

    // 3. Evidence tampering detection
    final tamperingResult = await _detectEvidenceTampering(evidenceFiles);
    details['evidence_tampering'] = tamperingResult;
    if (tamperingResult['detected']) {
      allChecksPassed = false;
    }

    // Determine overall status
    String status;
    if (allChecksPassed) {
      status = "passed";
    } else if (hasWarnings) {
      status = "warning";
    } else {
      status = "failed";
    }

    return MobileVerificationResult(
      status: status,
      details: details,
      locationConsistencyCheck: locationResult['passed'],
      evidenceSourceValid: sourceResult['all_valid'],
      evidenceTamperingDetected: tamperingResult['detected'],
    );
  }

  /// Check location consistency between report and evidence
  Future<Map<String, dynamic>> _checkLocationConsistency(
    Position reportLocation,
    List<Map<String, dynamic>> evidenceMetadata,
  ) async {
    final result = <String, dynamic>{
      'passed': true,
      'warning': false,
      'checks': [],
    };

    double reportLat = reportLocation.latitude;
    double reportLon = reportLocation.longitude;

    for (int i = 0; i < evidenceMetadata.length; i++) {
      final metadata = evidenceMetadata[i];
      final check = <String, dynamic>{
        'evidence_index': i,
        'has_gps_metadata': false,
        'distance_meters': null,
        'passed': true,
      };

      // Check if evidence has GPS metadata
      if (metadata['mediaLatitude'] != null && metadata['mediaLongitude'] != null) {
        double evidenceLat = metadata['mediaLatitude'];
        double evidenceLon = metadata['mediaLongitude'];
        
        check['has_gps_metadata'] = true;
        
        // Calculate distance between report and evidence locations
        double distance = Geolocator.distanceBetween(
          reportLat, reportLon, evidenceLat, evidenceLon
        );
        
        check['distance_meters'] = distance;
        
        // Allow up to 100 meters difference for consistency
        if (distance > 100) {
          check['passed'] = false;
          result['passed'] = false;
        }
        
        // Warn if distance is significant but within tolerance
        if (distance > 50) {
          check['warning'] = true;
          result['warning'] = true;
        }
      } else {
        // Missing GPS metadata is a warning, not failure
        check['warning'] = true;
        result['warning'] = true;
      }

      result['checks'].add(check);
    }

    return result;
  }

  /// Validate evidence source (detect downloaded content)
  Future<Map<String, dynamic>> _validateEvidenceSource(List<File> evidenceFiles) async {
    final result = <String, dynamic>{
      'all_valid': true,
      'files': [],
    };

    for (int i = 0; i < evidenceFiles.length; i++) {
      final file = evidenceFiles[i];
      final fileResult = <String, dynamic>{
        'file_index': i,
        'file_name': file.path.split('/').last,
        'is_downloaded': false,
        'is_screenshot': false,
        'valid': true,
      };

      try {
        // Check file extension and path for indicators of downloaded content
        String fileName = file.path.toLowerCase();
        
        // Check for common download indicators
        if (fileName.contains('download') || 
            fileName.contains('save') ||
            fileName.contains('cache') ||
            fileName.contains('temp')) {
          fileResult['is_downloaded'] = true;
          fileResult['valid'] = false;
          result['all_valid'] = false;
        }

        // For images, check if it's a screenshot
        if (fileName.endsWith('.jpg') || fileName.endsWith('.jpeg') || fileName.endsWith('.png')) {
          final isScreenshot = await _detectScreenshot(file);
          if (isScreenshot) {
            fileResult['is_screenshot'] = true;
            fileResult['valid'] = false;
            result['all_valid'] = false;
          }
        }

        // Check file creation time vs current time
        DateTime fileCreated = await file.lastModified();
        DateTime now = DateTime.now();
        Duration timeDiff = now.difference(fileCreated);
        
        // If file was created more than 12 hours ago, it might be old content
        if (timeDiff.inHours > 12) {
          fileResult['old_file'] = true;
          fileResult['valid'] = false;
          result['all_valid'] = false;
        }

      } catch (e) {
        fileResult['error'] = e.toString();
        fileResult['valid'] = false;
        result['all_valid'] = false;
      }

      result['files'].add(fileResult);
    }

    return result;
  }

  /// Detect evidence tampering (screenshots, screen recordings)
  Future<Map<String, dynamic>> _detectEvidenceTampering(List<File> evidenceFiles) async {
    final result = <String, dynamic>{
      'detected': false,
      'files': [],
    };

    for (int i = 0; i < evidenceFiles.length; i++) {
      final file = evidenceFiles[i];
      final fileResult = <String, dynamic>{
        'file_index': i,
        'file_name': file.path.split('/').last,
        'is_screenshot': false,
        'is_screen_recording': false,
        'suspicious_metadata': false,
      };

      try {
        String fileName = file.path.toLowerCase();

        // Check for screenshots
        if (fileName.endsWith('.jpg') || fileName.endsWith('.jpeg') || fileName.endsWith('.png')) {
          final isScreenshot = await _detectScreenshot(file);
          fileResult['is_screenshot'] = isScreenshot;
          
          if (isScreenshot) {
            result['detected'] = true;
          }
        }

        // Check for screen recordings (common indicators)
        if (fileName.endsWith('.mp4') || fileName.endsWith('.mov') || fileName.endsWith('.avi')) {
          final isScreenRecording = await _detectScreenRecording(file);
          fileResult['is_screen_recording'] = isScreenRecording;
          
          if (isScreenRecording) {
            result['detected'] = true;
          }
        }

        // Check for suspicious metadata
        final suspiciousMetadata = await _checkSuspiciousMetadata(file);
        fileResult['suspicious_metadata'] = suspiciousMetadata;
        
        if (suspiciousMetadata) {
          result['detected'] = true;
        }

      } catch (e) {
        fileResult['error'] = e.toString();
      }

      result['files'].add(fileResult);
    }

    return result;
  }

  /// Detect if an image is a screenshot
  Future<bool> _detectScreenshot(File imageFile) async {
    try {
      final bytes = await imageFile.readAsBytes();
      final image = img.decodeImage(bytes);
      
      if (image == null) return false;

      // Common screenshot dimensions
      final commonScreenshotResolutions = [
        [1920, 1080], [1366, 768], [1536, 864], [1440, 900],
        [1280, 720], [1600, 900], [2560, 1440], [1920, 1200],
        // Mobile resolutions
        [1080, 1920], [1080, 2340], [1080, 2400], [1125, 2436],
        [1242, 2688], [1170, 2532], [1284, 2778],
      ];

      // Check if resolution matches common screenshot sizes
      for (final resolution in commonScreenshotResolutions) {
        if ((image.width == resolution[0] && image.height == resolution[1]) ||
            (image.height == resolution[0] && image.width == resolution[1])) {
          return true;
        }
      }

      // Check EXIF data for screenshot indicators
      final exifData = await readExifFromBytes(bytes);
      if (exifData.isEmpty) {
        // No EXIF data is common for screenshots
        return true;
      }

      // Check for software that creates screenshots
      final software = exifData['Image Software'];
      if (software != null && software.toString().toLowerCase().contains('screenshot')) {
        return true;
      }

    } catch (e) {
      // If we can't analyze, assume it's not a screenshot
    }

    return false;
  }

  /// Detect if a video is a screen recording
  Future<bool> _detectScreenRecording(File videoFile) async {
    try {
      // This is a simplified detection - in production, you'd want to use
      // a proper video analysis library
      String fileName = videoFile.path.toLowerCase();
      
      // Check filename for screen recording indicators
      final screenRecordingIndicators = [
        'screen', 'record', 'capture', 'mirror', 'cast',
        'zoom', 'teams', 'meet', 'recorded'
      ];
      
      for (final indicator in screenRecordingIndicators) {
        if (fileName.contains(indicator)) {
          return true;
        }
      }

      // Check file size - screen recordings often have specific patterns
      int fileSize = await videoFile.length();
      
      // Very small video files might be suspicious
      if (fileSize < 100 * 1024) { // Less than 100KB
        return true;
      }

    } catch (e) {
      // If we can't analyze, assume it's not a screen recording
    }

    return false;
  }

  /// Check for suspicious metadata
  Future<bool> _checkSuspiciousMetadata(File file) async {
    try {
      String fileName = file.path.toLowerCase();
      
      // Check for suspicious patterns in filename
      final suspiciousPatterns = [
        'copy', 'duplicate', 'clone', 'fake', 'edited',
        'modified', 'altered', 'photoshop', 'edit'
      ];
      
      for (final pattern in suspiciousPatterns) {
        if (fileName.contains(pattern)) {
          return true;
        }
      }

      // For images, check EXIF for editing software
      if (fileName.endsWith('.jpg') || fileName.endsWith('.jpeg') || fileName.endsWith('.png')) {
        final bytes = await file.readAsBytes();
        final exifData = await readExifFromBytes(bytes);
        
        final software = exifData['Image Software'];
        if (software != null) {
          final softwareStr = software.toString().toLowerCase();
          final editingSoftware = [
            'photoshop', 'gimp', 'paint', 'editor', 'preview'
          ];
          
          for (final editor in editingSoftware) {
            if (softwareStr.contains(editor)) {
              return true;
            }
          }
        }
      }

    } catch (e) {
      // If we can't analyze, assume no suspicious metadata
    }

    return false;
  }
}
