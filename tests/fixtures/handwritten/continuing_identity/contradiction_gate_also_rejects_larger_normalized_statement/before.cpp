void process() {
    if (old_count) {
        consume(old_count);
    }
    flush_results();
    consume(old_count);
}
