I am developing a plan to greatly enhance my benchmarking solutions. ai agents are encouraged to improve this doc

this is for move detection and not clone detection, so we require some changes to bigclonebench to make it testable with clones. 

The author of this doc is not an expert on the structure of bigclonebench. How exactly we structure this program is not a major concern. The primary concern is making a reproducable benchmark suite that measures this repository's performance against the bigclonebench dataset. 

Do not fight the structure of bigclonebench if these instructions don't align well. focus on the goal of testing how well srcmove detects different types of clones. 

## What is a clone/move?

bigclonebench is a huge suite of tests that is far better vetted than my own meagre test suite. For now, I prefer its findings over my own. what it considers a clone and a false positve has stronger weight than my own handmade tests. 

## Current status

srcmove does not detect enough moves, and it detects far too many false positives. I am concerned about the speed of srcmove. i want to make it run much faster. 

## Expand bigclonebench suite
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

A single command that can be run to determine how well a current implementation of srcmove fulfilles the bigclonebench test suite. it will time how long it takes to run each subsection of the benchmarks. focusing on srcMove, since it is the subject of this repo. a clean output will print out relevant results in an easy to read format on the cli. 

I have zero expectation of being able to detect type 4 moves/clones. 
