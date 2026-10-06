void work() {
int target = source + 17;
try { checkpoint(); } catch (...) { recover(); }
}
