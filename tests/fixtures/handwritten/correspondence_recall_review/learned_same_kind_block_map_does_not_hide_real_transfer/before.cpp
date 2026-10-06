void process() {
    {
        unique_a(state);
        transfer_payload(state);
        unique_b(state);
    }
    flush_results(state);
    {
    }
    {
        unique_c(state);
        transfer_payload(state);
        unique_d(state);
    }
}
