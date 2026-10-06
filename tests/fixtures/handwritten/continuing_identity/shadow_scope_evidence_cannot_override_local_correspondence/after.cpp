void process() {
    flush_results();
    int new_count = 1;
    consume(new_count);
    {
        int old_count = 1;
        consume(old_count);
    }
}
