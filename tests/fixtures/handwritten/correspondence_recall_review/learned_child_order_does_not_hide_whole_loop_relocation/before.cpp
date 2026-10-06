void process() {
    while (ready) {
        unique_a(state);
        transfer_payload(state);
        unique_b(state);
    }
    flush_results(state);
    {
        transfer_payload(state);
    }
}
