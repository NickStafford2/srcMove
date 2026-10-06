void worker() {
    while(first) {
        unique_b(state);
        padding_work(state);
        repeat_work(state);
        padding_work(state);
        unique_a(state);
    }
    while(second) {
        unique_d(state);
        padding_work(state);
        repeat_work(state);
        padding_work(state);
        unique_c(state);
    }
}
