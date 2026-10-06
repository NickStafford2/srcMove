if (old_mode) {
    if (alpha_ready) {
        prepare_alpha();
        process_alpha();
        finish_alpha();
    }
    while (old_pending) {
        drain_old();
    }
    if (beta_ready) {
        prepare_beta();
        process_beta();
        finish_beta();
    }
}
