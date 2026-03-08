#import "foo.hpp"

int main(int argc, char **argv) {
  int a = changed_function();
  char c = unchanged_function();
  return 1;
}
