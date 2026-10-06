protected void zipFile(File from, File to) {
    FileInputStream in = new FileInputStream(from);
    ZipOutputStream out = new ZipOutputStream(to);
    byte[] buffer = new byte[4096];
    int bytes_read;
    while ((bytes_read = in.read(buffer)) != -1) out.write(buffer, 0, bytes_read);
    in.close();
    out.close();
}
