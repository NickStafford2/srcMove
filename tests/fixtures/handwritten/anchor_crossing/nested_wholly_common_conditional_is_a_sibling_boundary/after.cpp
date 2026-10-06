void work() {
    if (outer) {
        if (inner) {
            checkpoint();
        }
    }
    int target = source + 17;
}
