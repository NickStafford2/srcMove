void process() {
    flush_results(state);
    while (ready) {
        unique_a(state);
        transfer_payload(state);
        unique_b(state);
    }
    {
        transfer_payload(state);
    }
}
