void process() {
    {
    }
    flush_results(state);
    {
        unique_a(state);
        transfer_payload(state);
        unique_b(state);
    }
    {
        unique_c(state);
        transfer_payload(state);
        unique_d(state);
    }
}
