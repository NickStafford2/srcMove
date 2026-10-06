void process() {
    flush_results();
    if (new_count) {
        consume(new_count);
    }
    consume(actual_count);
}
