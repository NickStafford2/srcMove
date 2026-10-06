void process() {
    transfer_payload(state);
    while (ready) {
        flush_results(state);
    }
}
