#import "foo.hpp"

char coppied_function() { return 'a'; }

int main(int argc, char **argv) {
  int a = changed_function();
  char c = unchanged_function();
  return 1;
}
