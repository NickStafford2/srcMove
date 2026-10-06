void worker() {
    while(first) {
        unique_a(state);
        padding_work(state);
        repeat_work(state);
        padding_work(state);
        unique_b(state);
    }
    while(second) {
        unique_c(state);
        padding_work(state);
        repeat_work(state);
        padding_work(state);
        unique_d(state);
    }
}
