# IK character classification regression

Run from a Linux checkout with a C++17 compiler and Python 3:

```sh
python3 unittest/storage/fts/run_ik_char_util_test.py
python3 unittest/storage/fts/run_ik_char_util_test.py --sanitizers --build-dir build_fts_sanitizers
python3 unittest/storage/fts/run_ik_char_util_test.py --bench
```

The runner compiles the real production classifier, Unicode predicates and
decoder. It exports the original header from the specified `--baseline-ref`
(default: the competition implementation baseline), renames its class/include
guard, and compiles both versions into the same executable. A frozen copy of
the previous classification sequence is also checked. For a checkout whose Git
metadata belongs to another OS, export the original header with that OS's Git
and pass `--baseline-header PATH` instead.

The test suppresses expected malformed-input log messages and accesses the
internal charset-specialized function to avoid requiring a server's collation
registry. It checks return values and output types for all Unicode scalar
values, every truncated prefix, all one/two-byte sequences, 250,000 deterministic
random three/four-byte sequences, and null inputs. The optional microbenchmark
alternates baseline/optimized order over five samples of generated ASCII, CJK,
fullwidth, supplementary and mixed Unicode corpora. This measures only the
classifier; it cannot establish SQL performance or a competition score.

# TOKENIZE and MATCH integration comparison

Use the same server configuration for the original and optimized binaries:

```sh
python3 unittest/storage/fts/check_fts_semantics.py --record build_fts_checks/fts-original.json
# Restart the dedicated instance with the optimized binary.
python3 unittest/storage/fts/check_fts_semantics.py --compare build_fts_checks/fts-original.json
```

Use `--mysql-command 'mysql -hHOST -PPORT -uUSER'` for another endpoint and
`MYSQL_PWD` when needed. Each invocation creates a unique temporary database
and drops it on completion. Existing databases are not reused. Recording refuses
to overwrite an existing snapshot. The comparison covers both IK modes and
BENG, punctuation/connectors, embedded NUL, fullwidth characters, quantifiers,
mixed scripts, supplementary characters, category endpoints, repeated words,
and documents crossing the IK batch boundary. It compares all token contents
and frequencies, matching IDs and scores, ordered LIMIT results, and results
after index build and subsequent insert/update/delete. Expected results must
come from a real baseline instance; the script never fabricates a snapshot.

Run the official `tools/benchmark/fts_large_bench.sh` separately, unmodified,
with its full default parameters and `SKIP_LOAD=0` for both binaries. Neither
focused test replaces that end-to-end measurement or the existing `fts_index`
mysqltest suite.
