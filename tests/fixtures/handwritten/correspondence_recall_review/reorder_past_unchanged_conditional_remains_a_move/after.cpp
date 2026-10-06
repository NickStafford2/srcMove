void process() {
    if (ready) {
        flush_results(state);
    }
    transfer_payload(state);
}
