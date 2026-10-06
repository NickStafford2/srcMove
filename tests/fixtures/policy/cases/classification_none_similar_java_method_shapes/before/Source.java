class Source {
  int calculate(int value) {
    int doubled = value * 2;
    int limited = Math.min(doubled, 100);
    return limited;
  }
}
