void render(State *p, Output *out, bool all) {
    if (all || p->fpFmt != 0) {
        const char *format = p->fpFmt;
        append(out, " --fpfmt %s" , format ? format : "empty" );
    }
    if (p->lineLimit > 0) {
        append(out, " --linelimit %d" , p->lineLimit);
    }
    if (p->quote) {
        append(out, " --quote %s" , p->quote);
    }
}
