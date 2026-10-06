void process() {
    int old_count = 1;
    flush_results();
    consume(old_count);
    publish(other_count);
}
