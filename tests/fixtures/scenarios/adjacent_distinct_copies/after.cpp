void worker() {
    while (first) {
        unique_a(state);
        unique_b(state);
        repeat_work(state);
        other_repeat(state);
    }
    while (extra) {
        repeat_work(state);
        other_repeat(state);
    }
}
