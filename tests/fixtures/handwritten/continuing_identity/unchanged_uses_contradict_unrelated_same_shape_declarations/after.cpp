void process() {
    flush_results();
    int new_count = 1;
    consume(old_count);
    publish(new_count);
}
