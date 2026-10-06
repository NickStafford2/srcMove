void continuing_origin() {
    transfer_payload(state);
    unique_origin_context(state);
    flush_results(state);
}
void other_origin() {
}
void unknown_destination() {
    transfer_payload(state);
}
