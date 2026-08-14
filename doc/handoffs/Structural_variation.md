I am building a rather robust test suite. I have plenty of tests on detecting type 1 and type 2 clones. but for each one, the location of the moved code is identical in each BigCloneBench case.

I want you to develop a new test suite. maybe call it e2e_structural_diffs. the new test suite will take the same section of moved code, and change the structure of the blocks around it. so the moved code is the same, but where it is in its lexical context differs.

example, move from a class to a function.
moved from an empty block to a static void main.
moved from a struct in one file, to a function in another file.

i want you to write a script that generates every possible combination of blocks that a move could be in and make a test for it. then test to see if it works. if this is some huge Bit O, let me know.
