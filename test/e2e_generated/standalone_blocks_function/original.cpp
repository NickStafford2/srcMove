int foo() { return 123; }
int bar() { return 456; }

int main() {
  {
    foo();
  }
  {
    bar();
  }
  return 0;
}
