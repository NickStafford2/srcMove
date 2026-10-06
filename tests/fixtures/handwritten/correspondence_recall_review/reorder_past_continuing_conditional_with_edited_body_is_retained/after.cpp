void process() {
    if (ready) {
        flush_results(state);
        new_body_work(state);
    }
    transfer_payload(state);
}
