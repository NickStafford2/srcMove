#include "foo.hpp"

char coppied_function() { return 'a'; }

int changed_function() {
  int x = 123;
  int y = 456;
  return x;
}

char unchanged_function() {
  char a = 'a';
  char b = 'b';
  char c = 'c';
  return a + b + c;
}
