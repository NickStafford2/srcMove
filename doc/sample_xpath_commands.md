# Querying srcMove annotations

srcMove annotates accepted endpoints with the namespace
`http://www.srcML.org/srcMove`:

- `mv:id` identifies the shared move group;
- `mv:to` contains the destination XPath or XPath union on a deletion; and
- `mv:from` contains the source XPath or XPath union on an insertion.

The examples below use XMLStarlet and assume the annotated input is
`srcmove.xml`.

## List distinct move-group identifiers

```bash
xmlstarlet sel \
  -N mv="http://www.srcML.org/srcMove" \
  -t -m "//*[@mv:id]" -v "@mv:id" -n \
  srcmove.xml | sort -u
```

## List deletion-to-destination links

```bash
xmlstarlet sel \
  -N mv="http://www.srcML.org/srcMove" \
  -t -m "//*[@mv:to]" \
  -v "@mv:id" -o " -> " -v "@mv:to" -n \
  srcmove.xml
```

## List insertion-to-source links

```bash
xmlstarlet sel \
  -N mv="http://www.srcML.org/srcMove" \
  -t -m "//*[@mv:from]" \
  -v "@mv:id" -o " <- " -v "@mv:from" -n \
  srcmove.xml
```

## Extract every endpoint in one move group

Replace the example identifier with the `mv:id` of interest.

```bash
xmlstarlet sel \
  -N mv="http://www.srcML.org/srcMove" \
  -t -m "//*[@mv:id='97b1dcdaf']" -c "." -n \
  srcmove.xml
```

`mv:to` and `mv:from` are XPath expressions, and repeated-content groups may
store an XPath union separated by `|`. Consumers that evaluate those values
must bind the namespace prefixes used in the expression, including
`src=http://www.srcML.org/srcML/src`.
