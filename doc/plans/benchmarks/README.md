I am developing a plan to greatly enhance my benchmarking solutions. ai agents are encouraged to improve this doc

The author of this doc is not an expert on the structure of bigclonebench. How exactly we structure this program is not a major concern. The primary concern is making a reproducable benchmark suite that measures this repository's performance against the bigclonebench dataset. 

## what is a clone/move?

bigclonebench is a huge suite of tests that is far better vetted than my own meagre test suite. For now, I prefer its findings over my own. what it considers a clone and a false positve has stronger weight than my own handmade tests. 

## current status

srcmove does not detect enough moves, and it detects far too many false positives. I am concerned about the speed of srcmove. i want to make it run much faster. 

## expand bigclonebench suite
currently, we do not detect enough moves. 

99% of type 1 moves. 
50% of type 2 moves. 
type 3 moves not tested. 
type 4 moves not tested. 
false positives not tested.

I want to greatly expand my bigclonebench test suite. 
To test: 
% of type 1 moves
% of type 2 moves
% of type 3 moves
% of type 4 moves

% of type 1 false positives (if any exist)
% of type 2 false positives
% of type 3 false positives
% of type 4 false positives

## End goal

A single command that can be run to determine how well a current implementation of srcmove fulfilles the bigclonebench test suite. 
