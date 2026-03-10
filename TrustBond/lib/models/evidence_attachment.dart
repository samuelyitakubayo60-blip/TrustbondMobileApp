/// Represents a photo or video attachment before upload.
class EvidenceAttachment {
  final String path;
  final bool isVideo;
  final DateTime? capturedAt;
  final double? mediaLatitude;
  final double? mediaLongitude;
  final bool isLiveCapture;

  EvidenceAttachment({
    required this.path,
    required this.isVideo,
    this.capturedAt,
    this.mediaLatitude,
    this.mediaLongitude,
    this.isLiveCapture = false,
  });
}
