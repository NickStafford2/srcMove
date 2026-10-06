void process() {
    transfer_payload(state);
    if (ready) {
        flush_results(state);
    }
}
