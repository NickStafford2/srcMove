void process() {
    flush_results();
    if (foo.new_count) {
        consume(foo.new_count);
    }
    consume(actual_count);
}
