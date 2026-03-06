#include <string>

int foo() {
  int x = 123;
  return x;
}

int bar() {
  int y = 456;
  // srcdiff can not move this.
  std::string move_me = "I should be moved.";
  return y;
}

int main() {
  // This should be moved by srcdiff. but xml should be added.
  foo();

  // This should be moved by srcdiff. but xml should be added.
  bar();

  return 0;
}
