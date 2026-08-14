# Get all mv:partner inside a diff.xml
```
xmlstarlet sel \
-N mv="http://www.srcML.org/srcMove" \
-t -m "//*[@mv:partner]" \
-v "@mv:partner" -n \
diff_new.xml > diff_new.partner.xml

```

# Get all mv:partner inside a diff.xml
```
xmlstarlet sel \
-N mv="http://www.srcML.org/srcMove" \
-t -m "//*[@mv:partner]" \
-v "@mv:partners" -n \
diff_new.xml > diff_new.partners.xml

```

# Get all mv:move inside a diff.xml 
To see if every number from 1 to n are used. where n is the number of move ids.
```
xmlstarlet sel \
-N mv="http://www.srcML.org/srcMove" \
-t -m "//*[@mv:move]" \
-v "@mv:move" -n \
diff_new.xml | sort -n | uniq | nl

```
