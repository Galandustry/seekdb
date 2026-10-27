#!/usr/bin/env python3
"""Real-server IK differential over BMP CJK and dictionary range boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mysql-command', required=True)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('--record', type=Path)
group.add_argument('--compare', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
source = (root/'src/storage/fts/dict/ob_ik_dic.cpp').read_text()
words = re.findall(r'^\s*"([^"\\]*)"[,]?\s*$', source, re.M)
texts = [''.join(chr(c) for c in range(start, min(start+128, 0xa000)))
         for start in range(0x3400, 0xa000, 128)]
# Each 50k range continues to the end of its last leading character. Include
# words around each nominal cut and both adjacent first-character groups.
for cut in range(50000, len(words), 50000):
    left = cut
    right = cut
    while left > 0 and words[left-1][0] == words[cut][0]:
        left -= 1
    while right+1 < len(words) and words[right+1][0] == words[cut][0]:
        right += 1
    texts.extend(' '.join(words[max(0, i-10):i+11]) for i in (left, cut, right))
texts += ['', ' ', '\x00', 'a\x00中文', '𠀀😀𪛖', 'é Ω 한글 あ カ', '数据库 全文索引 分词器']
sql = ['SET NAMES utf8mb4; SET ob_query_timeout=100000000000;']
for mode in ('smart', 'max_word'):
    for text in texts:
        options = json.dumps([{'output':'all'},{'additional_args':[{'ik_mode':mode}]}])
        sql.append("SELECT TOKENIZE(CONVERT(X'"+text.encode().hex()+"' USING utf8mb4), 'ik', '"+options+"');")
client = shlex.split(args.mysql_command)+['--batch','--raw','--skip-column-names','--default-character-set=utf8mb4']
result = subprocess.run(client,input='\n'.join(sql),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
rows = [json.loads(line) for line in result.stdout.splitlines()]
assert len(rows) == len(texts)*2
record = {'corpus_sha256':hashlib.sha256(json.dumps(texts,ensure_ascii=False).encode()).hexdigest(), 'rows':rows}
if args.record:
    with args.record.open('x',encoding='utf-8') as out:
        json.dump(record,out,ensure_ascii=False)
else:
    assert record == json.loads(args.compare.read_text(encoding='utf-8')), 'IK range output changed'
print('PASS:',len(rows),'IK range boundary/Unicode results')
