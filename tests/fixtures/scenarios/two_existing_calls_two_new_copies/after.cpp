void worker() {
    while (first) {
        unique_a(state);
        unique_b(state);
        repeat_work(state);
    }
    while (second) {
        unique_c(state);
        unique_d(state);
        repeat_work(state);
    }
    while (extra_a) {
        repeat_work(state);
    }
    while (extra_b) {
        repeat_work(state);
    }
}
