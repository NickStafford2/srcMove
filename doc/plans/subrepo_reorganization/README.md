i notice that we have a number of embeaded git repositiries:
Deckard
sqlite
linux
notepadpp
opencv

We use these in benchmarking full repositories. these use an info.json for some benchmarkign tasks. they have a work directory inside them with three versions of the repos: original, modified, and repo. I am thinking of moving "repo" along with other src code repositires. into a separate folder somewhere in srcmove. perhaps in vendor/

this would be the standard locaiton for git clones and repositories. (not including srcmlbuildtemplate)

maybe if repository_analysis becmomes its own repo, it could be put there as well. but that is down the road and i may not want it. 


todo: must readd the school repo i use for my thesis documents. it is on my laptop but not here.
