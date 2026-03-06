// This currently can not be captured because srcdiff deletes the function tag
// and not the block.
int changed_function() {
  int x = 123;
  int y = 456;
  return x;
}

char unchanged_function();
char delcaration_moved();
