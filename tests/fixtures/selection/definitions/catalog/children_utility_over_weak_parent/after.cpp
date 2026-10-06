if (new_mode) {
    if (alpha_ready) {
        prepare_alpha();
        process_alpha();
        finish_alpha();
    }
    for (int i = 0;
    i < 1;
    ++i) {
        initialize_new();
    }
    if (beta_ready) {
        prepare_beta();
        process_beta();
        finish_beta();
    }
}
