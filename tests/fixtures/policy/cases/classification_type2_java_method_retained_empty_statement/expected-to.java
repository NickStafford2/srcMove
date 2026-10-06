int compute(int number) {
    int scaled = number * 2;
    ;
    int offset = scaled + 3;
    int reduced = offset - number;
    int answer = reduced * 4;
    return answer;
  }
