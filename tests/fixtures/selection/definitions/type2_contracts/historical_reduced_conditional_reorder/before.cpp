void render(State *p, Output *out, bool all) {
    if (p->lineLimit > 0) {
        append(out, " --linelimit %d" , p->lineLimit);
    }
    if (p->quote) {
        append(out, " --quote %s" , p->quote);
    }
    if (all || p->realFmt != 0) {
        const char *format = p->realFmt;
        append(out, " --realfmt %s" , format ? format : "default" );
    }
}
