# Get all mv:partner inside a srcmove.xml
```
xmlstarlet sel \
-N mv="http://www.srcML.org/srcMove" \
-t -m "//*[@mv:partner]" \
-v "@mv:partner" -n \
srcmove.xml > srcmove.partner.xml

```

# Get all mv:partner inside a srcmove.xml
```
xmlstarlet sel \
-N mv="http://www.srcML.org/srcMove" \
-t -m "//*[@mv:partner]" \
-v "@mv:partners" -n \
srcmove.xml > srcmove.partners.xml

```

# Get all mv:move inside a srcmove.xml
To see if every number from 1 to n are used. where n is the number of move ids.
```
xmlstarlet sel \
-N mv="http://www.srcML.org/srcMove" \
-t -m "//*[@mv:move]" \
-v "@mv:move" -n \
srcmove.xml | sort -n | uniq | nl

```
