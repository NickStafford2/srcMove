void work() {
try { checkpoint(); } catch (...) { recover(); }
int target = source + 17;
}
