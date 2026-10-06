void process() {
  flush_results();
  int new_count = 1;
  consume(new_count);
  publish_result();
}
