int foo() { return 123; }
int bar() { return 456; }

int main() {
  { bar(); }
  { foo(); }
  return 0;
}
