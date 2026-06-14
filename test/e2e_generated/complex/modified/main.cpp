#import "foo.hpp"

// This comment moves to a new file.

int main(int argc, char **argv) {
  int  a = changed_function();
  char c = unchanged_function();
  return 1;
}
