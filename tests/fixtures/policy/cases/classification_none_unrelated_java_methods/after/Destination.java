class Destination {
  String describe(boolean enabled) {
    if (enabled) {
      return "ready";
    }
    return "stopped";
  }
}
