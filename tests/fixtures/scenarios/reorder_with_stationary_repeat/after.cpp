void worker() {
    while (first) {
        padding_work(state);
        unique_a(state);
        padding_work(state);
        unique_b(state);
        padding_work(state);
        repeat_work(state);
    }
    while (second) {
        unique_c(state);
        unique_d(state);
        repeat_work(state);
    }
}
