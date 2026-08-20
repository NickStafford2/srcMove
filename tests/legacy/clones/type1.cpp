// A
int sum_first_n(int n) {
  int s = 0;
  for (int i = 1; i <= n; i++) {
    s += i;
  }
  return s;
}

// B (same tokens; only spacing/comments changed)
int sum_first_n(int n) {
  int s = 0;
  for (int i = 1; i <= n; i++) {
    s += i;
  }
  return s;
} // sums 1..n
