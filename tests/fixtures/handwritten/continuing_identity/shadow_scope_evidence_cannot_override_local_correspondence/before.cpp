void process() {
    int old_count = 1;
    flush_results();
    consume(old_count);
    {
        int old_count = 1;
        consume(old_count);
    }
}
