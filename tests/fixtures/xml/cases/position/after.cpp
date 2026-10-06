int changed_function() {
    int x = 123;
    int y = 456;
    return x;
}
#include "foo.hpp"
int main(int argc, char **argv) {
    int a = changed_function();
    return 1;
}
