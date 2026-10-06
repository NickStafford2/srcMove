void gotoURLWithMethod(String url) {
    int retries = 3;
    if (url != null) {
        connect(url);
    }
    log(url);
    close();
}
