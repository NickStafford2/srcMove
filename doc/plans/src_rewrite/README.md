this is a plan to possibly trump the deckard plan. 

the deckard plan seeks to imlement deckard algorithm. This may be advisable, but there seems like there could be dozens of viable move detection algorithms.I have been reading some papers and i have been looking at clone detection tools. I see many opportunities and things to try.

## master benchmark
But to do this, i need improved benchmarking and a much more robust test suite. 

The benchmarks plan in a sister directory goes over a plan to improve benchmarks. once that is done, perhaps we can do this. we may need improve tests. And perhaps we need a single benchmark command that can run all tests, run all benchmarks, and produce a result that allows me and ai's to be able to easily tell how well an implemenation works. 

## likely future work plans 
### git branch 
Make a separate git branch that has changes to the src directory. change srcmove's algorithms. and then run the master benchmark. compare to other branches

### separate src directories. 

make many versions of src. each can live beside each other and copy code. some of these benchmarks may be able to hook into srcmove cleanly, but others are different enough to need separate versions. 
with them all in the same root directory, we can build multiple versions of srcmove simultaneously. I kinda like this plan a bit more, but im not sold. 
