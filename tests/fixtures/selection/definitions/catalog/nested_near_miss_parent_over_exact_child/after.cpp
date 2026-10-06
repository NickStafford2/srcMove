if (newReady) {
    int marker = 1;
    validate();
    publish(newValue);
    cleanup();
}
