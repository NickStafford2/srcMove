void process() {
    flush_results();
    if (foo.new_count) {
        consume(foo.new_count);
    }
    {
        consume(foo.actual_count);
    }
}
