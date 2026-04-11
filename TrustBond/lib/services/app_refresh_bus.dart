import 'dart:async';

class AppRefreshBus {
  AppRefreshBus._();

  static final StreamController<String> _controller =
      StreamController<String>.broadcast();

  static Stream<String> get stream => _controller.stream;

  static void notify([String reason = 'generic']) {
    if (!_controller.isClosed) {
      _controller.add(reason);
    }
  }
}
