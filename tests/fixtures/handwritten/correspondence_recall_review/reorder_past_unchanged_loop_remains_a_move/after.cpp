void process() {
    while (ready) {
        flush_results(state);
    }
    transfer_payload(state);
}
