// A
int clamp0_100(int x) {
  if (x < 0) return 0;
  if (x > 100) return 100;
  return x;
}

// B (renamed identifiers + different literal)
int clamp0_255(int value) {
  if (value < 0) return 0;
  if (value > 255) return 255;
  return value;
}
