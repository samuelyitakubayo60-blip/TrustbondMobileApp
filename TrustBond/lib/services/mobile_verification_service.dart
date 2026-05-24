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

    // 2. Evidence source validation (uses per-file metadata, e.g. live capture)
    final sourceResult =
        await _validateEvidenceSource(evidenceFiles, evidenceMetadata);
    details['evidence_source'] = sourceResult;
    if (!sourceResult['all_valid']) {
      allChecksPassed = false;
    }

    // 3. Evidence tampering detection
    final tamperingResult = await _detectEvidenceTampering(evidenceFiles, evidenceMetadata);
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

  /// Validate evidence source (detect downloaded / third-party saved content).
  ///
  /// Note: Live photos are often copied into the app temp directory (`.../cache/...`),
  /// which must NOT be treated as "downloaded". Use [evidenceMetadata] `isLiveCapture`
  /// and TrustBond sanitize filename pattern `tb_*.jpg` to avoid false positives.
  Future<Map<String, dynamic>> _validateEvidenceSource(
    List<File> evidenceFiles,
    List<Map<String, dynamic>> evidenceMetadata,
  ) async {
    final result = <String, dynamic>{
      'all_valid': true,
      'files': [],
    };

    for (int i = 0; i < evidenceFiles.length; i++) {
      final file = evidenceFiles[i];
      final meta = i < evidenceMetadata.length ? evidenceMetadata[i] : {};
      final isLiveCapture = meta['isLiveCapture'] == true;
      final baseName = file.path.split('/').last.toLowerCase();
      final isTrustBondSanitized =
          RegExp(r'^tb_\d+\.jpg$').hasMatch(baseName);

      final fileResult = <String, dynamic>{
        'file_index': i,
        'file_name': file.path.split('/').last,
        'is_downloaded': false,
        'is_screenshot': false,
        'valid': true,
        'is_live_capture': isLiveCapture,
      };

      try {
        final pathLower = file.path.toLowerCase();

        // Strong third-party / download-folder signals only (not generic "cache"/"temp").
        final suspiciousThirdParty = [
          'whatsapp',
          'telegram',
          'instagram',
          'facebook',
          'twitter',
          'tiktok',
          '/download/',
          '\\download\\',
          'download_manager',
          'saved from',
          'forwarded',
        ];
        final looksThirdParty =
            suspiciousThirdParty.any((s) => pathLower.contains(s));

        if (!isLiveCapture &&
            !isTrustBondSanitized &&
            looksThirdParty) {
          fileResult['is_downloaded'] = true;
          fileResult['valid'] = false;
          result['all_valid'] = false;
        }

        // Screenshot check in source validation is redundant with tampering pass;
        // skip for live capture and our sanitized temp JPEGs (EXIF often stripped).
        if (!isLiveCapture &&
            !isTrustBondSanitized &&
            (pathLower.endsWith('.jpg') ||
                pathLower.endsWith('.jpeg') ||
                pathLower.endsWith('.png'))) {
          final isScreenshot = await _detectScreenshot(file);
          if (isScreenshot) {
            fileResult['is_screenshot'] = true;
            fileResult['valid'] = false;
            result['all_valid'] = false;
          }
        }

        final fileCreated = await file.lastModified();
        final now = DateTime.now();
        final timeDiff = now.difference(fileCreated);

        // Fresh captures (e.g. just written by sanitize) should never fail this.
        if (!isLiveCapture &&
            !isTrustBondSanitized &&
            timeDiff.inHours > 12) {
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
  Future<Map<String, dynamic>> _detectEvidenceTampering(
    List<File> evidenceFiles,
    List<Map<String, dynamic>> evidenceMetadata,
  ) async {
    final result = <String, dynamic>{
      'detected': false,
      'files': [],
    };

    for (int i = 0; i < evidenceFiles.length; i++) {
      final file = evidenceFiles[i];
      final meta = i < evidenceMetadata.length ? evidenceMetadata[i] : <String, dynamic>{};
      final isLive = meta['isLiveCapture'] == true;

      final fileResult = <String, dynamic>{
        'file_index': i,
        'file_name': file.path.split('/').last,
        'is_screenshot': false,
        'is_screen_recording': false,
        'suspicious_metadata': false,
      };

      try {
        String fileName = file.path.toLowerCase();

        // Live captures from the camera are trusted — skip tampering checks.
        if (isLive) {
          result['files'].add(fileResult);
          continue;
        }

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
          final isScreenRecording = await _detectScreenRecording(file, isLiveCapture: isLive);
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

      // Desktop / monitor resolutions only — phone camera photos often match
      // "mobile screenshot" sizes; treating those as screenshots causes massive false positives.
      final desktopScreenshotResolutions = [
        [1920, 1080],
        [1366, 768],
        [1536, 864],
        [1440, 900],
        [1280, 720],
        [1600, 900],
        [2560, 1440],
        [1920, 1200],
      ];

      for (final resolution in desktopScreenshotResolutions) {
        if ((image.width == resolution[0] && image.height == resolution[1]) ||
            (image.height == resolution[0] && image.width == resolution[1])) {
          return true;
        }
      }

      final exifData = await readExifFromBytes(bytes);
      // Re-encoded / pipeline-stripped JPEGs often have no EXIF — do not assume screenshot.
      if (exifData.isEmpty) {
        return false;
      }

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
  Future<bool> _detectScreenRecording(File videoFile, {bool isLiveCapture = false}) async {
    // Live captures from the camera are never screen recordings.
    if (isLiveCapture) return false;

    try {
      final fileName = videoFile.path.toLowerCase();

      // Only flag files whose names explicitly reference screen capture tools.
      final screenRecordingIndicators = [
        'screenrecord', 'screen_record', 'scrcpy', 'mirror', 'cast',
      ];

      for (final indicator in screenRecordingIndicators) {
        if (fileName.contains(indicator)) return true;
      }

      // Flag only truly empty/corrupt files (< 10 KB).
      // Real phone videos — even 1-second clips — are well above 100 KB.
      final fileSize = await videoFile.length();
      if (fileSize < 10 * 1024) return true;
    } catch (_) {
      // Cannot analyse — don't block.
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
