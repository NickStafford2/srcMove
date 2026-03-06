#include <string>

int foo() {
  int x = 123;
  std::string move_me = "I should be moved.";
  return x;
}

int bar() {
  int y = 456;
  // srcdiff can not move this.
  return y;
}

int main() {
  // This should be moved by srcdiff. but xml should be added.
  bar();

  // This should be moved by srcdiff. but xml should be added.
  foo();

  return 0;
}
