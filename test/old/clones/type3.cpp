// A
int sum_positive(const std::vector<int>& v) {
  int s = 0;
  for (int x : v) {
    if (x > 0) s += x;
  }
  return s;
}

// B (near-miss: extra statement + small condition change)
int sum_positive(const std::vector<int>& v) {
  int s = 0;
  for (int x : v) {
    if (x >= 0) s += x;   // changed > to >=
    if (x == 0) s += 10;  // inserted statement
  }
  return s;
}
