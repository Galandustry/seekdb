#!/usr/bin/env python3
# Copyright (c) 2025 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"""Compare actual TOKENIZE output and MATCH rows/scores with a baseline instance.

Uses only a uniquely named temporary database, removed on completion. This is a
correctness check, separate from the unchanged official performance benchmark.
"""

import argparse
import hashlib
import json
import pathlib
import shlex
import subprocess
import uuid


TEXTS = [
    "", " ", "\x00", "a", "A z 0 9", "abc ABC abc", "hello-world a_b x@y 1,234.56",
    "ＡＢＣ ａｂｃ １２３ 123 ＃＆＋－．＠＿", "中文全文检索 数据库 数据库",
    "三百二十个 12公斤 一万两千元", "中华人民共和国人民大会堂",
    "ひらがな カタカナ 한글 ㄱㄴㄷ", "😀𠀀🙂", "éñß İı Ω Ж",
    "\t\n\r!?,.;:-_#@&+", "数据库OceanBase123数据库abc", "abc\x00中文\x00def",
    # Character ranges on both sides of each classification boundary.
    "".join(chr(code) for code in [
        0x2f, 0x30, 0x39, 0x3a, 0x40, 0x41, 0x5a, 0x5b, 0x60, 0x61, 0x7a, 0x7b,
        0x303f, 0x3040, 0x309f, 0x30a0, 0x30ff, 0x3100, 0x3130, 0x318f, 0x3190,
        0x31f0, 0x31ff, 0x3200, 0x33ff, 0x3400, 0x4dbf, 0x4dc0, 0x4dff, 0x4e00,
        0x9fff, 0xa000, 0xabff, 0xac00, 0xd7af, 0xd7b0, 0xf8ff, 0xf900, 0xfaff,
        0xfb00, 0xfeff, 0xff00, 0xff10, 0xff19, 0xff21, 0xff3a, 0xff41, 0xff5a,
        0xffef, 0xfff0]),
    "a" * 999 + " 中文", "中" * 1000 + " 数据库",
    ("数据库abc 12公斤。" * 200) + "尾部tail", "z" * 1002,
]
QUERIES = ["abc", "数据库", "数据库 abc", "12 公斤", "中华人民共和国", "hello world", "不存在的词"]
PARSERS = [("ik", "smart"), ("ik", "max_word"), ("beng", None)]


def sql_text(text):
    return "CONVERT(X'" + text.encode("utf-8").hex() + "' USING utf8mb4)"


def config(mode):
    return json.dumps([{"output": "all"}] + (
        [{"additional_args": [{"ik_mode": mode}]}] if mode else []))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-command", default="mysql -h127.0.0.1 -P2881 -uroot")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", type=pathlib.Path, help="write original-version snapshot")
    mode.add_argument("--compare", type=pathlib.Path, help="compare optimized instance to snapshot")
    args = parser.parse_args()
    client = shlex.split(args.mysql_command) + ["--batch", "--raw", "--skip-column-names",
                                               "--default-character-set=utf8mb4"]
    database = "fts_semantics_" + uuid.uuid4().hex

    def execute(sql):
        result = subprocess.run(client, input=("SET NAMES utf8mb4; "
            "SET ob_query_timeout=100000000000; " + sql).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return result.stdout.decode("utf-8").splitlines()

    # Refuse to overwrite evidence from another build accidentally.
    if args.record and args.record.exists():
        parser.error(f"Snapshot already exists: {args.record}")
    snapshot = {"format": 1, "corpus_sha256": hashlib.sha256(json.dumps(
        [TEXTS, QUERIES, PARSERS], ensure_ascii=False).encode("utf-8")).hexdigest(),
        "tokenize": {}, "match": {}}
    execute(f"CREATE DATABASE {database};")
    try:
        for analyzer, ik_mode in PARSERS:
            name = analyzer + ("_" + ik_mode if ik_mode else "")
            for index, text in enumerate(TEXTS):
                sql = (f"SELECT TOKENIZE({sql_text(text)}, '{analyzer}', "
                       f"'{config(ik_mode)}');")
                rows = execute(sql)
                if len(rows) != 1:
                    raise AssertionError(f"Unexpected TOKENIZE row count: {name}/{index}")
                snapshot["tokenize"][f"{name}/{index}"] = json.loads(rows[0])

            table = f"{database}.{name}"
            execute(f"CREATE TABLE {table}(id INT PRIMARY KEY, body TEXT) CHARSET=utf8mb4;")
            values = [f"({i}, {sql_text(text)})" for i, text in enumerate(TEXTS)]
            execute(f"INSERT INTO {table} VALUES " + ",".join(values) + ";")
            properties = f' PARSER_PROPERTIES=(ik_mode="{ik_mode}")' if ik_mode else ""
            execute(f"ALTER TABLE {table} ADD FULLTEXT INDEX ft(body) WITH PARSER {analyzer}"
                    + properties + ";")

            def collect(stage):
                for number, query in enumerate(QUERIES):
                    match = f"MATCH(body) AGAINST({sql_text(query)})"
                    for limit in [False, True]:
                        # Include every matching ID and score, and ordered top-k,
                        # instead of using hit counts as a correctness oracle.
                        sql = f"SELECT id, {match} FROM {table} WHERE {match} ORDER BY "
                        sql += f"{match} DESC, id LIMIT 5;" if limit else "id;"
                        key = f"{name}/{stage}/{number}/limit={limit}"
                        snapshot["match"][key] = execute(sql)

            collect("build")
            execute(f"UPDATE {table} SET body={sql_text('数据库 abc 123')} WHERE id=0;")
            execute(f"DELETE FROM {table} WHERE id=1;")
            execute(f"INSERT INTO {table} VALUES (100, {sql_text('尾部tail 数据库 abc')});")
            collect("dml")
    finally:
        execute(f"DROP DATABASE {database};")

    if args.record:
        args.record.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print(f"Recorded {len(snapshot['tokenize'])} TOKENIZE and {len(snapshot['match'])} MATCH results")
    else:
        expected = json.loads(args.compare.read_text(encoding="utf-8"))
        if expected != snapshot:
            for category in ["tokenize", "match"]:
                for key, value in snapshot[category].items():
                    if expected.get(category, {}).get(key) != value:
                        raise AssertionError(f"Changed {category} result: {key}\n"
                            f"baseline={expected.get(category, {}).get(key)!r}\nactual={value!r}")
            raise AssertionError("Snapshot format/corpus mismatch")
        print(f"PASS: {len(snapshot['tokenize'])} TOKENIZE and {len(snapshot['match'])} MATCH results unchanged")


if __name__ == "__main__":
    main()
