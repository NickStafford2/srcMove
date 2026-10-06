void process(int old_count, int new_count) {
  {
    flush_results();
    int new_count = 1;
    consume(old_count);
    publish(new_count);
  }
}
