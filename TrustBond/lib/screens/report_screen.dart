// ignore_for_file: use_build_context_synchronously, deprecated_member_use

import 'dart:io';
import 'package:flutter/material.dart';

import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, TargetPlatform, kIsWeb, kDebugMode, debugPrint;

import 'package:geolocator/geolocator.dart';

import 'package:image_picker/image_picker.dart';
import 'package:exif/exif.dart';

import '../services/api_service.dart';

import '../services/device_service.dart';

import '../services/motion_service.dart';

import '../models/report_model.dart';

import '../models/evidence_attachment.dart';

import 'package:trustbond/services/mobile_verification_service.dart';

/// Camera works only on Android/iOS. On Windows/Web use gallery.

bool get _isMobileWithCamera =>

    !kIsWeb &&

    (defaultTargetPlatform == TargetPlatform.android ||

        defaultTargetPlatform == TargetPlatform.iOS);



class ReportScreen extends StatefulWidget {

  const ReportScreen({super.key});



  @override

  State<ReportScreen> createState() => _ReportScreenState();

}



class _ReportScreenState extends State<ReportScreen> {

  final _formKey = GlobalKey<FormState>();

  final _descriptionController = TextEditingController();

  final _apiService = ApiService();

  final _deviceService = DeviceService();

  final ImagePicker _picker = ImagePicker();



  String? _deviceId;

  List<dynamic> _incidentTypes = [];

  int? _selectedIncidentTypeId;

  bool _incidentTypesLoading = false;

  Position? _currentPosition;

  double? _gpsAccuracy;

  bool _isSubmitting = false;

  final List<EvidenceAttachment> _attachments = [];

  double? _exifToDouble(dynamic value) {
    // exif package may return Ratio / IfdRatios / num / String.
    try {
      if (value == null) return null;
      if (value is num) return value.toDouble();
      final s = value.toString();
      // Ratio typically renders as "123/100" or "12"
      if (s.contains('/')) {
        final parts = s.split('/');
        if (parts.length == 2) {
          final a = double.tryParse(parts[0].trim());
          final b = double.tryParse(parts[1].trim());
          if (a != null && b != null && b != 0) return a / b;
        }
      }
      return double.tryParse(s.trim());
    } catch (_) {
      return null;
    }
  }

  double? _exifGpsToDecimal(dynamic gpsValues, String? ref) {
    try {
      if (gpsValues == null) return null;
      final list = gpsValues is List ? gpsValues : null;
      if (list == null || list.length < 3) return null;
      final deg = _exifToDouble(list[0]);
      final min = _exifToDouble(list[1]);
      final sec = _exifToDouble(list[2]);
      if (deg == null || min == null || sec == null) return null;
      var dec = deg + (min / 60.0) + (sec / 3600.0);
      final r = (ref ?? '').toUpperCase().trim();
      if (r == 'S' || r == 'W') dec = -dec;
      return dec;
    } catch (_) {
      return null;
    }
  }

  DateTime? _parseExifDateTime(dynamic value) {
    try {
      if (value == null) return null;
      final s = value.toString().trim();
      // EXIF often uses "YYYY:MM:DD HH:MM:SS"
      if (s.length >= 19 && s[4] == ':' && s[7] == ':' && s[10] == ' ') {
        final yyyy = int.parse(s.substring(0, 4));
        final mm = int.parse(s.substring(5, 7));
        final dd = int.parse(s.substring(8, 10));
        final hh = int.parse(s.substring(11, 13));
        final mi = int.parse(s.substring(14, 16));
        final ss = int.parse(s.substring(17, 19));
        return DateTime(yyyy, mm, dd, hh, mi, ss);
      }
      // fallback to DateTime.parse if it happens to be ISO-like
      return DateTime.tryParse(s);
    } catch (_) {
      return null;
    }
  }

  Future<({DateTime? capturedAt, double? lat, double? lon, bool hasExif, String? error})>
      _readImageExifForAttachment(String filePath) async {
    try {
      final bytes = await File(filePath).readAsBytes();
      final Map<String, IfdTag> exifData = await readExifFromBytes(bytes);
      if (exifData.isEmpty) {
        return (capturedAt: null, lat: null, lon: null, hasExif: false, error: null);
      }

      // Keys vary; try common ones.
      final dt =
          _parseExifDateTime(exifData['EXIF DateTimeOriginal']?.printable) ??
          _parseExifDateTime(exifData['Image DateTime']?.printable) ??
          _parseExifDateTime(exifData['EXIF DateTimeDigitized']?.printable);

      final lat = _exifGpsToDecimal(
        exifData['GPS GPSLatitude']?.values,
        exifData['GPS GPSLatitudeRef']?.printable,
      );
      final lon = _exifGpsToDecimal(
        exifData['GPS GPSLongitude']?.values,
        exifData['GPS GPSLongitudeRef']?.printable,
      );

      return (capturedAt: dt, lat: lat, lon: lon, hasExif: true, error: null);
    } catch (e) {
      return (capturedAt: null, lat: null, lon: null, hasExif: false, error: e.toString());
    }
  }



  @override

  void initState() {

    super.initState();

    _initializeDevice();

    _loadIncidentTypes();

    _getCurrentLocation();

  }



  Future<void> _initializeDevice() async {

    final deviceHash = await _deviceService.getDeviceHash();

    try {

      final deviceData = await _apiService.registerDevice(deviceHash);

      setState(() {

        _deviceId = deviceData['device_id'];

      });

      await _deviceService.saveDeviceId(_deviceId!);

    } catch (e) {

      ScaffoldMessenger.of(context).showSnackBar(

        SnackBar(content: Text('Failed to register device: $e')),

      );

    }

  }



  Future<void> _loadIncidentTypes() async {

    setState(() {

      _incidentTypesLoading = true;

    });

    try {

      final types = await _apiService.getIncidentTypes();

      setState(() {

        _incidentTypes = types;

      });

    } catch (e) {

      ScaffoldMessenger.of(context).showSnackBar(

        SnackBar(content: Text('Failed to load incident types: $e')),

      );

    } finally {

      if (mounted) {

        setState(() {

          _incidentTypesLoading = false;

        });

      }

    }

  }



  Future<void> _takePhoto() async {

    if (!_isMobileWithCamera) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          const SnackBar(

              content: Text('Camera is available on Android/iOS. Use Gallery to add a photo.')),

        );

      }

      return;

    }

    try {

      final XFile? photo = await _picker.pickImage(

        source: ImageSource.camera,

        imageQuality: 85,

      );

      if (photo != null && mounted) {

        setState(() {

          _attachments.add(EvidenceAttachment(

            path: photo.path,

            isVideo: false,

            capturedAt: DateTime.now(),

            mediaLatitude: _currentPosition?.latitude,

            mediaLongitude: _currentPosition?.longitude,

            isLiveCapture: true,

          ));

        });

      }

    } catch (e) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          SnackBar(content: Text('Failed to take photo: $e')),

        );

      }

    }

  }



  Future<void> _recordVideo() async {

    if (!_isMobileWithCamera) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          const SnackBar(

              content: Text('Camera is available on Android/iOS. Use Video to add from gallery.')),

        );

      }

      return;

    }

    try {

      final XFile? video = await _picker.pickVideo(

        source: ImageSource.camera,

        maxDuration: const Duration(minutes: 2),

      );

      if (video != null && mounted) {

        setState(() {

          _attachments.add(EvidenceAttachment(

            path: video.path,

            isVideo: true,

            capturedAt: DateTime.now(),

            mediaLatitude: _currentPosition?.latitude,

            mediaLongitude: _currentPosition?.longitude,

            isLiveCapture: true,

          ));

        });

      }

    } catch (e) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          SnackBar(content: Text('Failed to record video: $e')),

        );

      }

    }

  }



  Future<void> _pickImage() async {

    try {

      final XFile? image = await _picker.pickImage(

        source: ImageSource.gallery,

        imageQuality: 85,

      );

      if (image != null && mounted) {

        setState(() {

          // Gallery selection: try to extract EXIF capture time and GPS when available.
          // If EXIF missing (common after edits / some share flows), we keep nulls and backend will treat as warning.
          _attachments.add(EvidenceAttachment(

            path: image.path,

            isVideo: false,

            capturedAt: null,
            mediaLatitude: null,
            mediaLongitude: null,
            isLiveCapture: false,

          ));

        });

        // Populate EXIF asynchronously (avoid blocking UI thread).
        final exif = await _readImageExifForAttachment(image.path);
        if (!mounted) return;
        setState(() {
          final idx = _attachments.lastIndexWhere((a) => a.path == image.path);
          if (idx >= 0) {
            final existing = _attachments[idx];
            _attachments[idx] = EvidenceAttachment(
              path: existing.path,
              isVideo: existing.isVideo,
              capturedAt: exif.capturedAt ?? existing.capturedAt,
              mediaLatitude: exif.lat ?? existing.mediaLatitude,
              mediaLongitude: exif.lon ?? existing.mediaLongitude,
              isLiveCapture: existing.isLiveCapture,
              hasExif: exif.hasExif,
              exifParseError: exif.error,
            );
          }
        });

      }

    } catch (e) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          SnackBar(content: Text('Failed to pick image: $e')),

        );

      }

    }

  }



  Future<void> _pickVideo() async {

    try {

      final XFile? video = await _picker.pickVideo(source: ImageSource.gallery);

      if (video != null && mounted) {

        setState(() {

          _attachments.add(EvidenceAttachment(

            path: video.path,

            isVideo: true,

            // Gallery video: EXIF is not reliable; use filesystem modified time as a best-effort timestamp.
            capturedAt: null,
            mediaLatitude: null,
            mediaLongitude: null,
            isLiveCapture: false,

          ));

        });

        // Best-effort timestamp for videos
        try {
          final ts = await File(video.path).lastModified();
          if (!mounted) return;
          setState(() {
            final idx = _attachments.lastIndexWhere((a) => a.path == video.path);
            if (idx >= 0) {
              final existing = _attachments[idx];
              _attachments[idx] = EvidenceAttachment(
                path: existing.path,
                isVideo: existing.isVideo,
                capturedAt: existing.capturedAt ?? ts,
                mediaLatitude: existing.mediaLatitude,
                mediaLongitude: existing.mediaLongitude,
                isLiveCapture: existing.isLiveCapture,
                hasExif: false,
                exifParseError: null,
              );
            }
          });
        } catch (_) {}

      }

    } catch (e) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          SnackBar(content: Text('Failed to pick video: $e')),

        );

      }

    }

  }



  void _removeAttachment(int index) {

    setState(() {

      _attachments.removeAt(index);

    });

  }



  void _showMediaOptions() {

    showModalBottomSheet(

      context: context,

      builder: (context) => SafeArea(

        child: Column(

          mainAxisSize: MainAxisSize.min,

          children: [

            if (_isMobileWithCamera) ...[

              ListTile(

                leading: const Icon(Icons.camera_alt),

                title: const Text('Take Photo'),

                onTap: () {

                  Navigator.pop(context);

                  _takePhoto();

                },

              ),

              ListTile(

                leading: const Icon(Icons.videocam),

                title: const Text('Record Video'),

                onTap: () {

                  Navigator.pop(context);

                  _recordVideo();

                },

              ),

            ],

            ListTile(

              leading: const Icon(Icons.photo_library),

              title: const Text('Pick Photo from Gallery'),

              onTap: () {

                Navigator.pop(context);

                _pickImage();

              },

            ),

            ListTile(

              leading: const Icon(Icons.video_library),

              title: const Text('Pick Video from Gallery'),

              onTap: () {

                Navigator.pop(context);

                _pickVideo();

              },

            ),

            if (!_isMobileWithCamera)

              const Padding(

                padding: EdgeInsets.all(16.0),

                child: Text(

                  'Camera options available on mobile devices',

                  style: TextStyle(fontSize: 12, color: Colors.grey),

                  textAlign: TextAlign.center,

                ),

              ),

          ],

        ),

      ),

    );

  }



  Future<void> _getCurrentLocation() async {

    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();

    if (!serviceEnabled) {

      ScaffoldMessenger.of(context).showSnackBar(

        const SnackBar(content: Text('Location services are disabled')),

      );

      return;

    }



    LocationPermission permission = await Geolocator.checkPermission();

    if (permission == LocationPermission.denied) {

      permission = await Geolocator.requestPermission();

      if (permission == LocationPermission.denied) {

        ScaffoldMessenger.of(context).showSnackBar(

          const SnackBar(content: Text('Location permissions are denied')),

        );

        return;

      }

    }



    if (permission == LocationPermission.deniedForever) {

      ScaffoldMessenger.of(context).showSnackBar(

        const SnackBar(content: Text('Location permissions are permanently denied')),

      );

      return;

    }



    try {

      final position = await Geolocator.getCurrentPosition(

        desiredAccuracy: LocationAccuracy.high,

      );

      setState(() {

        _currentPosition = position;

        _gpsAccuracy = position.accuracy;

      });

    } catch (e) {

      ScaffoldMessenger.of(context).showSnackBar(

        SnackBar(content: Text('Failed to get location: $e')),

      );

    }

  }



  Future<void> _submitReport() async {

    if (!_formKey.currentState!.validate()) {

      return;

    }



    if (_deviceId == null) {

      ScaffoldMessenger.of(context).showSnackBar(

        const SnackBar(content: Text('Device not registered')),

      );

      return;

    }



    if (_selectedIncidentTypeId == null) {

      ScaffoldMessenger.of(context).showSnackBar(

        const SnackBar(content: Text('Please select an incident type')),

      );

      return;

    }



    if (_currentPosition == null) {

      ScaffoldMessenger.of(context).showSnackBar(

        const SnackBar(content: Text('Location not available')),

      );

      return;

    }



    setState(() {

      _isSubmitting = true;

    });



    try {

      // Collect motion/accelerometer data before submit

      MotionSample motion = await collectMotionSample(durationSeconds: 1.2);

      // Perform mobile rule-based verification
      final verificationService = MobileVerificationService();
      final evidenceFiles = _attachments.map((att) => File(att.path)).toList();
      final evidenceMetadata = _attachments.map((att) => {
        'mediaLatitude': att.mediaLatitude,
        'mediaLongitude': att.mediaLongitude,
        'capturedAt': att.capturedAt?.toIso8601String(),
        'isLiveCapture': att.isLiveCapture,
      }).toList();

      final mobileVerification = await verificationService.verifyReport(
        reportLocation: _currentPosition!,
        evidenceFiles: evidenceFiles,
        evidenceMetadata: evidenceMetadata,
      );

      if (kDebugMode) {
        debugPrint('Mobile verification result: ${mobileVerification.status}');
        debugPrint('Location consistency: ${mobileVerification.locationConsistencyCheck}');
        debugPrint('Evidence source valid: ${mobileVerification.evidenceSourceValid}');
        debugPrint('Tampering detected: ${mobileVerification.evidenceTamperingDetected}');
      }

      // Block submission if verification fails due to non-original evidence
      if (mobileVerification.status == "failed") {
        String errorMessage = "Cannot submit report: ";
        
        if (!mobileVerification.evidenceSourceValid) {
          errorMessage += "Evidence appears to be downloaded or not original. Please use original photos/videos taken at the scene.";
        } else if (mobileVerification.evidenceTamperingDetected) {
          errorMessage += "Evidence appears to be a screenshot or screen recording. Please use original photos/videos taken at the scene.";
        } else if (!mobileVerification.locationConsistencyCheck) {
          errorMessage += "Evidence location does not match report location. Please ensure evidence was taken at the reported location.";
        } else {
          errorMessage += "Evidence verification failed. Please use original photos/videos taken at the scene.";
        }
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(errorMessage),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 5),
          ),
        );
        setState(() => _isSubmitting = false);
        return;
      }

      // Show warning if verification has warnings but allow submission
      if (mobileVerification.status == "warning") {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text("Warning: Some evidence may not be original. Report will be submitted but may be flagged for review."),
            backgroundColor: Colors.orange,
            duration: const Duration(seconds: 3),
          ),
        );
      }

      final report = ReportModel(

        deviceId: _deviceId!,

        incidentTypeId: _selectedIncidentTypeId!,

        description: _descriptionController.text.isEmpty

            ? null

            : _descriptionController.text,

        latitude: _currentPosition!.latitude,

        longitude: _currentPosition!.longitude,

        gpsAccuracy: _gpsAccuracy,

        motionLevel: motion.motionLevel,

        movementSpeed: motion.movementSpeed,

        wasStationary: motion.wasStationary,

      );

      // Add mobile verification results to report data
      final reportData = report.toJson();
      reportData.addAll(mobileVerification.toJson());

      final result = await _apiService.submitReport(reportData);

      final reportId = result['report_id'] as String?;



      if (reportId != null && _attachments.isNotEmpty) {

        for (final attachment in _attachments) {

          await _apiService.uploadEvidence(

            reportId,

            _deviceId!,

            attachment.path,

            mediaLatitude: attachment.mediaLatitude,

            mediaLongitude: attachment.mediaLongitude,

            capturedAt: attachment.capturedAt,

            isLiveCapture: attachment.isLiveCapture,

          );

        }

      }



      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          const SnackBar(content: Text('Report submitted successfully!')),

        );

        _descriptionController.clear();

        setState(() {

          _selectedIncidentTypeId = null;

          _attachments.clear();

        });

      }

    } catch (e) {

      if (mounted) {

        ScaffoldMessenger.of(context).showSnackBar(

          SnackBar(content: Text('Failed to submit report: $e')),

        );

      }

    } finally {

      if (mounted) {

        setState(() {

          _isSubmitting = false;

        });

      }

    }

  }



  @override

  Widget build(BuildContext context) {

    return Scaffold(

      body: SingleChildScrollView(

        padding: const EdgeInsets.all(16.0),

        child: Form(

          key: _formKey,

          child: Column(

            crossAxisAlignment: CrossAxisAlignment.stretch,

            children: [

              DropdownButtonFormField<int>(

                initialValue: _selectedIncidentTypeId,

                decoration: const InputDecoration(

                  labelText: 'Incident Type',

                  border: OutlineInputBorder(),

                ),

                items: _incidentTypes.map((type) {

                  return DropdownMenuItem<int>(

                    value: type['incident_type_id'],

                    child: Text(type['type_name']),

                  );

                }).toList(),

                onChanged: (_incidentTypesLoading || _incidentTypes.isEmpty)

                    ? null

                    : (value) {

                        setState(() {

                          _selectedIncidentTypeId = value;

                        });

                      },

                validator: (value) {

                  if (value == null) {

                    return 'Please select an incident type';

                  }

                  return null;

                },

              ),

              if (_incidentTypesLoading) ...[

                const SizedBox(height: 8),

                const Row(

                  children: [

                    SizedBox(

                      width: 16,

                      height: 16,

                      child: CircularProgressIndicator(strokeWidth: 2),

                    ),

                    SizedBox(width: 8),

                    Text('Loading incident types...'),

                  ],

                ),

              ] else if (_incidentTypes.isEmpty) ...[

                const SizedBox(height: 8),

                const Text(

                  'No incident types available. Please check backend seeding.',

                  style: TextStyle(color: Colors.red),

                ),

              ],

              const SizedBox(height: 16),

              TextFormField(

                controller: _descriptionController,

                decoration: const InputDecoration(

                  labelText: 'Description (Optional)',

                  border: OutlineInputBorder(),

                ),

                maxLines: 4,

              ),

              const SizedBox(height: 16),

              const Text(

                'Evidence (optional)',

                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),

              ),

              const SizedBox(height: 8),

              SizedBox(

                width: double.infinity,

                child: OutlinedButton.icon(

                  onPressed: _isSubmitting ? null : _showMediaOptions,

                  icon: const Icon(Icons.add_photo_alternate),

                  label: const Text('Add Evidence'),

                  style: OutlinedButton.styleFrom(

                    padding: const EdgeInsets.symmetric(vertical: 12),

                  ),

                ),

              ),

              if (_attachments.isNotEmpty) ...[

                const SizedBox(height: 12),

                SizedBox(

                  height: 100,

                  child: ListView.builder(

                    scrollDirection: Axis.horizontal,

                    itemCount: _attachments.length,

                    itemBuilder: (context, index) {

                      final a = _attachments[index];

                      return Padding(

                        padding: const EdgeInsets.only(right: 8),

                        child: Stack(

                          children: [

                            ClipRRect(

                              borderRadius: BorderRadius.circular(8),

                              child: a.isVideo

                                  ? const SizedBox(

                                      width: 80,

                                      height: 80,

                                      child: ColoredBox(

                                        color: Colors.black87,

                                        child: Icon(

                                          Icons.videocam,

                                          color: Colors.white,

                                          size: 32,

                                        ),

                                      ),

                                    )

                                  : Image.file(

                                      File(a.path),

                                      width: 80,

                                      height: 80,

                                      fit: BoxFit.cover,

                                    ),

                            ),

                            Positioned(

                              top: 4,

                              right: 4,

                              child: GestureDetector(

                                onTap: () => _removeAttachment(index),

                                child: const CircleAvatar(

                                  radius: 14,

                                  backgroundColor: Colors.red,

                                  child: Icon(Icons.close, color: Colors.white, size: 18),

                                ),

                              ),

                            ),

                          ],

                        ),

                      );

                    },

                  ),

                ),

                Text(

                  '${_attachments.length} file(s) attached',

                  style: Theme.of(context).textTheme.bodySmall,

                ),

              ],

              const SizedBox(height: 16),

              if (_currentPosition != null)

                Card(

                  child: Padding(

                    padding: const EdgeInsets.all(16.0),

                    child: Column(

                      crossAxisAlignment: CrossAxisAlignment.start,

                      children: [

                        const Text(

                          'Location:',

                          style: TextStyle(fontWeight: FontWeight.bold),

                        ),

                        Text('Lat: ${_currentPosition!.latitude.toStringAsFixed(7)}'),

                        Text('Lng: ${_currentPosition!.longitude.toStringAsFixed(7)}'),

                        if (_gpsAccuracy != null)

                          Text('Accuracy: ${_gpsAccuracy!.toStringAsFixed(2)}m'),

                      ],

                    ),

                  ),

                ),

              const SizedBox(height: 24),

              ElevatedButton(

                onPressed: _isSubmitting ? null : _submitReport,

                style: ElevatedButton.styleFrom(

                  padding: const EdgeInsets.symmetric(vertical: 16),

                ),

                child: _isSubmitting

                    ? const CircularProgressIndicator()

                    : const Text('Submit Report'),

              ),

            ],

          ),

        ),

      ),

    );

  }



  @override

  void dispose() {

    _descriptionController.dispose();

    super.dispose();

  }

}

