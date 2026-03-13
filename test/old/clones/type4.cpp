// A (iterative)
long long fact_iter(int n) {
  long long r = 1;
  for (int i = 2; i <= n; i++) r *= i;
  return r;
}

// B (recursive)
long long fact_rec(int n) {
  if (n <= 1) return 1;
  return n * fact_rec(n - 1);
}
