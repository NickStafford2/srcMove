#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${BCB_WORK_DIR:-"$ROOT_DIR/test/bigclonebench"}"
BCE_DIR="$WORK_DIR/BigCloneEval"
DOWNLOAD_DIR="$WORK_DIR/downloads"
EXPORT_DIR="$WORK_DIR/export"

BCE_REPO="${BCE_REPO:-https://github.com/jeffsvajlenko/BigCloneEval.git}"
BCE_REF="${BCE_REF:-master}"

BCB_URL="${BCB_URL:-https://1drv.ms/u/s!AhXbM6MKt_yLj_NwwVacvUzmi6uorA?e=eMu0P4}"
IJA_URL="${IJA_URL:-https://1drv.ms/u/s!AhXbM6MKt_yLj_N15CewgjM7Y8NLKA?e=cScoRJ}"

BCB_TARBALL="${BCB_TARBALL:-"$DOWNLOAD_DIR/BigCloneBench_BCEvalVersion.tar.gz"}"
IJA_TARBALL="${IJA_TARBALL:-"$DOWNLOAD_DIR/IJaDataset_BCEvalVersion.tar.gz"}"

DOWNLOAD=1
EXTRACT_IJA=1
EXPORT_ALL_TABLES=1

usage() {
  cat <<'EOF'
Usage: scripts/setup_bigclonebench.sh [options]

Downloads and prepares BigCloneEval/BigCloneBench under test/bigclonebench,
then exports the H2 benchmark database to CSV/TSV files.

Options:
  --no-download       Use existing tarballs instead of downloading them.
  --no-ijadataset     Do not download/extract the reduced IJaDataset archive.
  --metadata-only     Export table/column metadata, not full table CSV files.
  -h, --help          Show this help.

Environment overrides:
  BCB_WORK_DIR        Output root. Default: test/bigclonebench
  BCE_REPO            BigCloneEval git URL.
  BCE_REF             BigCloneEval ref/branch/tag. Default: master
  BCB_URL             BigCloneBench H2 database tarball URL.
  IJA_URL             BigCloneEval reduced IJaDataset tarball URL.
  BCB_TARBALL         Existing/downloaded BigCloneBench tarball path.
  IJA_TARBALL         Existing/downloaded IJaDataset tarball path.

Generated outputs:
  test/bigclonebench/BigCloneEval/
  test/bigclonebench/export/tables/*.csv
  test/bigclonebench/export/table_columns.tsv
  test/bigclonebench/export/table_counts.tsv
  test/bigclonebench/export/candidate_clone_tables.tsv
  test/bigclonebench/export/manifest.txt
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-download)
      DOWNLOAD=0
      ;;
    --no-ijadataset)
      EXTRACT_IJA=0
      ;;
    --metadata-only)
      EXPORT_ALL_TABLES=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 2
  fi
}

download_file() {
  local url="$1"
  local out="$2"

  if [[ -s "$out" ]]; then
    echo "using existing download: $out"
    return
  fi

  echo "downloading: $url"
  mkdir -p "$(dirname "$out")"
  curl -L --fail --retry 3 --retry-delay 2 -o "$out" "$url"
}

assert_tarball() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "error: missing archive: $path" >&2
    exit 2
  fi
  if ! tar -tzf "$path" >/dev/null 2>&1; then
    echo "error: not a readable .tar.gz archive: $path" >&2
    echo "       OneDrive may have returned an HTML login/download page." >&2
    echo "       Download manually, then rerun with BCB_TARBALL/IJA_TARBALL and --no-download." >&2
    exit 2
  fi
}

clone_bigcloneeval() {
  if [[ -d "$BCE_DIR/.git" ]]; then
    echo "updating BigCloneEval checkout"
    git -C "$BCE_DIR" fetch --tags origin
  else
    echo "cloning BigCloneEval into $BCE_DIR"
    mkdir -p "$WORK_DIR"
    git clone "$BCE_REPO" "$BCE_DIR"
  fi

  git -C "$BCE_DIR" checkout "$BCE_REF"
}

extract_archives() {
  mkdir -p "$BCE_DIR/bigclonebenchdb" "$BCE_DIR/ijadataset"

  echo "extracting BigCloneBench DB into $BCE_DIR/bigclonebenchdb"
  tar -xzf "$BCB_TARBALL" -C "$BCE_DIR/bigclonebenchdb"

  if [[ "$EXTRACT_IJA" -eq 1 ]]; then
    echo "extracting reduced IJaDataset into $BCE_DIR/ijadataset"
    tar -xzf "$IJA_TARBALL" -C "$BCE_DIR/ijadataset"
  fi
}

find_h2_jar() {
  find "$BCE_DIR" -type f -name 'h2*.jar' | sort | head -n 1
}

find_bcb_db_base() {
  local db_file
  db_file="$(find "$BCE_DIR/bigclonebenchdb" -type f \( \
    -name 'bcb.h2.db' -o \
    -name 'bcb.mv.db' -o \
    -name 'bcb.data.db' -o \
    -name 'bcb.*.db' \
  \) | sort | head -n 1)"

  if [[ -z "$db_file" ]]; then
    echo "error: could not find an H2 bcb database file under $BCE_DIR/bigclonebenchdb" >&2
    exit 2
  fi

  case "$db_file" in
    *.h2.db) printf '%s\n' "${db_file%.h2.db}" ;;
    *.mv.db) printf '%s\n' "${db_file%.mv.db}" ;;
    *.data.db) printf '%s\n' "${db_file%.data.db}" ;;
    *) printf '%s\n' "${db_file%.*}" ;;
  esac
}

write_exporter() {
  local java_file="$1"
  mkdir -p "$(dirname "$java_file")"
  cat > "$java_file" <<'EOF'
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class ExportBigCloneBench {
  record TableRef(String schema, String name) {}

  public static void main(String[] args) throws Exception {
    if (args.length != 3) {
      throw new IllegalArgumentException("usage: ExportBigCloneBench <jdbc-url> <out-dir> <export-all:true|false>");
    }

    String jdbcUrl = args[0];
    Path outDir = Path.of(args[1]);
    boolean exportAll = Boolean.parseBoolean(args[2]);

    Files.createDirectories(outDir);
    Files.createDirectories(outDir.resolve("tables"));

    try (Connection conn = DriverManager.getConnection(jdbcUrl, "sa", "")) {
      DatabaseMetaData meta = conn.getMetaData();
      List<TableRef> tables = loadTables(meta);

      try (
        BufferedWriter columns = Files.newBufferedWriter(outDir.resolve("table_columns.tsv"), StandardCharsets.UTF_8);
        BufferedWriter counts = Files.newBufferedWriter(outDir.resolve("table_counts.tsv"), StandardCharsets.UTF_8);
        BufferedWriter candidates = Files.newBufferedWriter(outDir.resolve("candidate_clone_tables.tsv"), StandardCharsets.UTF_8)
      ) {
        columns.write("schema\ttable\tordinal\tcolumn\ttype\tnullable\n");
        counts.write("schema\ttable\trows\n");
        candidates.write("schema\ttable\treason\n");

        for (TableRef table : tables) {
          Set<String> columnNames = writeColumns(meta, table, columns);
          long rowCount = countRows(conn, table);
          counts.write(nullToEmpty(table.schema()) + "\t" + table.name() + "\t" + rowCount + "\n");

          String reason = cloneTableReason(columnNames);
          if (!reason.isEmpty()) {
            candidates.write(nullToEmpty(table.schema()) + "\t" + table.name() + "\t" + reason + "\n");
          }

          if (exportAll) {
            exportCsv(conn, table, outDir.resolve("tables").resolve(safeFileName(table) + ".csv"));
          }
        }
      }
    }
  }

  static List<TableRef> loadTables(DatabaseMetaData meta) throws Exception {
    List<TableRef> tables = new ArrayList<>();
    try (ResultSet rs = meta.getTables(null, null, "%", new String[]{"TABLE"})) {
      while (rs.next()) {
        String schema = rs.getString("TABLE_SCHEM");
        String name = rs.getString("TABLE_NAME");
        if (schema != null && schema.equalsIgnoreCase("INFORMATION_SCHEMA")) {
          continue;
        }
        tables.add(new TableRef(schema, name));
      }
    }
    tables.sort((a, b) -> qualifiedName(a).compareToIgnoreCase(qualifiedName(b)));
    return tables;
  }

  static Set<String> writeColumns(DatabaseMetaData meta, TableRef table, BufferedWriter out) throws Exception {
    Set<String> names = new HashSet<>();
    try (ResultSet rs = meta.getColumns(null, table.schema(), table.name(), "%")) {
      while (rs.next()) {
        String column = rs.getString("COLUMN_NAME");
        names.add(column.toLowerCase(Locale.ROOT));
        out.write(nullToEmpty(table.schema()));
        out.write("\t");
        out.write(table.name());
        out.write("\t");
        out.write(Integer.toString(rs.getInt("ORDINAL_POSITION")));
        out.write("\t");
        out.write(column);
        out.write("\t");
        out.write(rs.getString("TYPE_NAME"));
        out.write("\t");
        out.write(Integer.toString(rs.getInt("NULLABLE")));
        out.write("\n");
      }
    }
    return names;
  }

  static String cloneTableReason(Set<String> columns) {
    if (columns.contains("function_id_one") && columns.contains("function_id_two")) {
      return "has function_id_one/function_id_two";
    }
    if (columns.contains("functionality_id") && columns.contains("syntactic_type")) {
      return "has functionality_id/syntactic_type";
    }
    if (columns.contains("similarity_token") && columns.contains("similarity_line")) {
      return "has similarity metrics";
    }
    return "";
  }

  static long countRows(Connection conn, TableRef table) throws Exception {
    try (
      Statement stmt = conn.createStatement();
      ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM " + quotedQualifiedName(table))
    ) {
      rs.next();
      return rs.getLong(1);
    }
  }

  static void exportCsv(Connection conn, TableRef table, Path outFile) throws Exception {
    try (
      Statement stmt = conn.createStatement();
      ResultSet rs = stmt.executeQuery("SELECT * FROM " + quotedQualifiedName(table));
      BufferedWriter out = Files.newBufferedWriter(outFile, StandardCharsets.UTF_8)
    ) {
      ResultSetMetaData md = rs.getMetaData();
      int cols = md.getColumnCount();
      for (int i = 1; i <= cols; i++) {
        if (i > 1) out.write(",");
        writeCsv(out, md.getColumnLabel(i));
      }
      out.write("\n");

      while (rs.next()) {
        for (int i = 1; i <= cols; i++) {
          if (i > 1) out.write(",");
          Object value = rs.getObject(i);
          writeCsv(out, value == null ? "" : value.toString());
        }
        out.write("\n");
      }
    }
  }

  static void writeCsv(BufferedWriter out, String value) throws IOException {
    out.write('"');
    for (int i = 0; i < value.length(); i++) {
      char c = value.charAt(i);
      if (c == '"') out.write("\"\"");
      else out.write(c);
    }
    out.write('"');
  }

  static String quotedQualifiedName(TableRef table) {
    if (table.schema() == null || table.schema().isBlank()) {
      return quote(table.name());
    }
    return quote(table.schema()) + "." + quote(table.name());
  }

  static String qualifiedName(TableRef table) {
    if (table.schema() == null || table.schema().isBlank()) return table.name();
    return table.schema() + "." + table.name();
  }

  static String quote(String ident) {
    return "\"" + ident.replace("\"", "\"\"") + "\"";
  }

  static String nullToEmpty(String value) {
    return value == null ? "" : value;
  }

  static String safeFileName(TableRef table) {
    return qualifiedName(table).replaceAll("[^A-Za-z0-9_.-]+", "_");
  }
}
EOF
}

export_database() {
  local h2_jar db_base jdbc_url exporter_dir exporter_java export_all

  h2_jar="$(find_h2_jar)"
  if [[ -z "$h2_jar" ]]; then
    echo "error: could not find h2*.jar in $BCE_DIR" >&2
    exit 2
  fi

  db_base="$(find_bcb_db_base)"
  jdbc_url="jdbc:h2:$db_base;IFEXISTS=TRUE"
  exporter_dir="$WORK_DIR/exporter"
  exporter_java="$exporter_dir/ExportBigCloneBench.java"
  export_all="true"
  if [[ "$EXPORT_ALL_TABLES" -eq 0 ]]; then
    export_all="false"
  fi

  rm -rf "$EXPORT_DIR"
  mkdir -p "$EXPORT_DIR"
  write_exporter "$exporter_java"

  echo "compiling H2 exporter"
  javac -cp "$h2_jar" "$exporter_java"

  echo "exporting BigCloneBench DB from $jdbc_url"
  java -cp "$h2_jar:$exporter_dir" ExportBigCloneBench "$jdbc_url" "$EXPORT_DIR" "$export_all"

  {
    echo "work_dir=$WORK_DIR"
    echo "bigcloneeval_repo=$BCE_REPO"
    echo "bigcloneeval_ref_requested=$BCE_REF"
    echo "bigcloneeval_ref_actual=$(git -C "$BCE_DIR" rev-parse HEAD)"
    echo "bcb_tarball=$BCB_TARBALL"
    echo "ija_tarball=$IJA_TARBALL"
    echo "h2_jar=$h2_jar"
    echo "h2_db_base=$db_base"
    echo "export_all_tables=$export_all"
  } > "$EXPORT_DIR/manifest.txt"
}

main() {
  need_cmd git
  need_cmd tar
  need_cmd java
  need_cmd javac
  if [[ "$DOWNLOAD" -eq 1 ]]; then
    need_cmd curl
  fi

  mkdir -p "$DOWNLOAD_DIR"

  clone_bigcloneeval

  if [[ "$DOWNLOAD" -eq 1 ]]; then
    download_file "$BCB_URL" "$BCB_TARBALL"
    if [[ "$EXTRACT_IJA" -eq 1 ]]; then
      download_file "$IJA_URL" "$IJA_TARBALL"
    fi
  fi

  assert_tarball "$BCB_TARBALL"
  if [[ "$EXTRACT_IJA" -eq 1 ]]; then
    assert_tarball "$IJA_TARBALL"
  fi

  extract_archives
  export_database

  echo
  echo "BigCloneBench setup complete."
  echo "Export directory: $EXPORT_DIR"
}

main "$@"
