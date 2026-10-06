void worker() {
    while(merged) {
        unique_a(state);
        padding_work(state);
        repeat_work(state);
        padding_work(state);
        unique_b(state);
    }
    while(other) {
        repeat_work(state);
    }
}
