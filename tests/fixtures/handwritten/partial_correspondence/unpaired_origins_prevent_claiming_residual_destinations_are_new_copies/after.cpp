void worker() {
    while(keep_running) {
        unique_a(state);
        unique_b(state);
        repeat_work(state);
    }
    while(new_unknown) {
        repeat_work(state);
    }
}
