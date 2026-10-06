void continuing_origin() {
    transfer_payload(state);
    unique_origin_context(state);
    flush_results(state);
}
void other_origin() {
    transfer_payload(state);
}
void unknown_destination() {
}
