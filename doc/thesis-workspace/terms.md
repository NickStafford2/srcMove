# Token
A lexical token from source code, not a word or character.

The code is first run through a lexer (tokenizer), just like in a compiler. That process breaks raw source text into meaningful atomic units such as:

- keywords (if, for, while, return)
- identifiers (myVar, calculateSum)
- literals (42, "hello")
- operators (+, ==, <=)
- punctuation / symbols ({, }, (, ))
