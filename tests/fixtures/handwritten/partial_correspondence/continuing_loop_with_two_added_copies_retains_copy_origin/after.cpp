void worker() {
    while(keep_running) {
        unique_a(state);
        unique_b(state);
        repeat_work(state);
    }
    while(extra_a) {
        repeat_work(state);
    }
    while(extra_b) {
        repeat_work(state);
    }
}
