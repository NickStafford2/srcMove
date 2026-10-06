void worker() {
    while(left) {
        unique_a(state);
        padding_work(state);
        repeat_work(state);
    }
    while(right) {
        padding_work(state);
        unique_b(state);
        repeat_work(state);
    }
}
