void process(int old_count, int new_count) {
  {
    int old_count = 1;
    flush_results();
    consume(old_count);
    publish(new_count);
  }
}
