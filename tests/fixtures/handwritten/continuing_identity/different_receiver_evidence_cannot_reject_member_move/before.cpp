void process() {
    if (foo.old_count) {
        consume(foo.old_count);
    }
    flush_results();
    {
        consume(bar.old_count);
    }
}
