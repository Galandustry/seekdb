/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Focused native test, with no server or dictionary dependency. See README.md.
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

#include "lib/charset/ob_charset.h"
#include "lib/charset/ob_charset_string_helper.h"
#include "lib/oblog/ob_log_module.h"
#include "storage/fts/utils/unicode_utils.h"

// Exercise the internal charset-specialized classifier without linking the
// server's collation registry. Silence expected malformed-input warnings only.
#undef STORAGE_FTS_LOG
#define STORAGE_FTS_LOG(...)
#define private public
#include "storage/fts/ik/ob_ik_char_util.h"
#undef private

// The comparison runner supplies an unmodified baseline header, renaming only
// its class and include guard so both versions coexist in this process.
#ifdef FTS_BASELINE_HEADER
#define private public
#include FTS_BASELINE_HEADER
#undef private
#endif

using namespace oceanbase::common;
using namespace oceanbase::storage;
using CharType = ObFTCharUtil::CharType;

namespace
{
uint64_t checked = 0;

// Preserve the previous classification algorithm as a differential oracle.
// The individual predicates and Unicode decoder are production code.
template <ObCharsetType CS_TYPE>
int legacy_classify(const char *input, uint8_t char_len, CharType &type)
{
  int ret = OB_SUCCESS;
  bool checker = false;
  type = CharType::USELESS;
  if (OB_FAIL(ObFTCharUtil::is_alpha<CS_TYPE>(input, char_len, checker))) {
  } else if (checker) {
    type = CharType::ENGLISH_LETTER;
  } else if (OB_FAIL(ObFTCharUtil::is_arabic<CS_TYPE>(input, char_len, checker))) {
  } else if (checker) {
    type = CharType::ARABIC_LETTER;
  } else if (OB_FAIL(ObFTCharUtil::is_chinese<CS_TYPE>(input, char_len, checker))) {
  } else if (checker) {
    type = CharType::CHINESE;
  } else if (OB_FAIL(ObFTCharUtil::is_other_cjk<CS_TYPE>(input, char_len, checker))) {
  } else if (checker) {
    type = CharType::OTHER_CJK;
  } else if (OB_FAIL(ObFTCharUtil::is_surrogate_high<CS_TYPE>(input, char_len, checker))) {
  } else if (checker) {
    type = CharType::SURROGATE_HIGH;
  } else if (OB_FAIL(ObFTCharUtil::is_surrogate_low<CS_TYPE>(input, char_len, checker))) {
  } else if (checker) {
    type = CharType::SURROGATE_LOW;
  }
  return ret;
}

template <ObCharsetType CS_TYPE>
void check(const char *input, uint8_t len)
{
  CharType expected = CharType::CHINESE;
  CharType actual = CharType::CHINESE;
  const int expected_ret = legacy_classify<CS_TYPE>(input, len, expected);
  const int actual_ret = ObFTCharUtil::do_classify<CS_TYPE>(input, len, actual);
  if (actual_ret != expected_ret || actual != expected) {
    std::fprintf(stderr, "Mismatch charset=%d len=%u ret=%d/%d type=%d/%d\n",
        CS_TYPE, len, actual_ret, expected_ret, int(actual), int(expected));
    std::abort();
  }
#ifdef FTS_BASELINE_HEADER
  BaselineFTCharUtil::CharType baseline_type = BaselineFTCharUtil::CharType::CHINESE;
  const int baseline_ret = BaselineFTCharUtil::do_classify<CS_TYPE>(input, len, baseline_type);
  if (actual_ret != baseline_ret || int(actual) != int(baseline_type)) {
    std::fprintf(stderr, "Mismatch with original baseline header\n");
    std::abort();
  }
#endif
  ++checked;
}

void check_all_charsets(const char *input, uint8_t len)
{
  check<CHARSET_UTF8MB4>(input, len);
  check<CHARSET_UTF16>(input, len);
  check<CHARSET_UTF16LE>(input, len);
}

void correctness()
{
  // Every Unicode scalar value, including all category endpoints, fullwidth
  // overlaps, supplementary CJK, emoji, NUL, and noncharacters.
  unsigned char buf[4] = {};
  for (ob_wc_t code = 0; code <= 0x10ffff; ++code) {
    if (code >= 0xd800 && code <= 0xdfff) { continue; }
    const int len = ob_charset_encode_unicode<CHARSET_UTF8MB4>(code, buf, buf + sizeof(buf));
    if (len <= 0) { std::abort(); }
    check<CHARSET_UTF8MB4>(reinterpret_cast<const char *>(buf), len);
    // Every proper prefix must retain its original error and output type.
    for (int prefix = 0; prefix < len; ++prefix) {
      check<CHARSET_UTF8MB4>(reinterpret_cast<const char *>(buf), prefix);
    }
  }

  // Exhaust all byte values and pairs, including bad continuation bytes,
  // overlong encodings and isolated UTF-8 lead/continuation bytes. UTF-16
  // specializations are compared as implemented, without redefining them.
  for (unsigned int first = 0; first < 256; ++first) {
    buf[0] = first;
    check_all_charsets(reinterpret_cast<const char *>(buf), 1);
    for (unsigned int second = 0; second < 256; ++second) {
      buf[1] = second;
      check_all_charsets(reinterpret_cast<const char *>(buf), 2);
    }
  }

  std::mt19937 rng(0x5eed);
  for (int i = 0; i < 250000; ++i) {
    for (auto &byte : buf) { byte = rng() & 0xff; }
    check_all_charsets(reinterpret_cast<const char *>(buf), 3);
    check_all_charsets(reinterpret_cast<const char *>(buf), 4);
  }
  for (uint8_t len = 0; len <= 4; ++len) { check_all_charsets(nullptr, len); }
  std::printf("PASS: %llu classifier comparisons (return code and output type)\n",
      static_cast<unsigned long long>(checked));
}

struct Character
{
  std::array<char, 4> data;
  uint8_t len;
};

template <typename Classifier>
double measure(const std::vector<Character> &corpus, Classifier classify, uint64_t &checksum)
{
  const auto start = std::chrono::steady_clock::now();
  uint64_t sum = 0;
  for (int repeat = 0; repeat < 1000; ++repeat) {
    for (const auto &ch : corpus) {
      CharType type;
      const int ret = classify(ch.data.data(), ch.len, type);
      sum += static_cast<uint64_t>(ret + int(type));
    }
  }
  checksum = sum;
  return std::chrono::duration<double, std::milli>(
      std::chrono::steady_clock::now() - start).count();
}

void benchmark()
{
  // A generated Unicode corpus, independent of the official SQL/data. Keep
  // separate ASCII, CJK, fullwidth, supplementary and mixed measurements.
  const std::array<std::pair<ob_wc_t, ob_wc_t>, 5> ranges = {{
      {0x20, 0x7e}, {0x3400, 0x9fff}, {0xff00, 0xffef},
      {0x10000, 0x10ffff}, {0x20, 0x10ffff}}};
  const char *names[] = {"ascii", "cjk", "fullwidth", "supplementary", "mixed"};
  std::mt19937 rng(0x5eed);
  for (size_t group = 0; group < ranges.size(); ++group) {
    std::vector<Character> corpus;
    while (corpus.size() < 4096) {
      const auto range = ranges[group];
      const ob_wc_t code = range.first + rng() % (range.second - range.first + 1);
      if (code >= 0xd800 && code <= 0xdfff) { continue; }
      Character ch;
      ch.len = ob_charset_encode_unicode<CHARSET_UTF8MB4>(code,
          reinterpret_cast<unsigned char *>(ch.data.data()),
          reinterpret_cast<unsigned char *>(ch.data.data() + ch.data.size()));
      corpus.push_back(ch);
    }
    for (int sample = 0; sample < 5; ++sample) {
      uint64_t before_sum = 0, after_sum = 0;
      auto before = [](const char *p, uint8_t len, CharType &type) {
#ifdef FTS_BASELINE_HEADER
        BaselineFTCharUtil::CharType baseline_type;
        const int ret = BaselineFTCharUtil::do_classify<CHARSET_UTF8MB4>(p, len, baseline_type);
        type = static_cast<CharType>(baseline_type);
        return ret;
#else
        return legacy_classify<CHARSET_UTF8MB4>(p, len, type);
#endif
      };
      auto after = [](const char *p, uint8_t len, CharType &type) {
        return ObFTCharUtil::do_classify<CHARSET_UTF8MB4>(p, len, type);
      };
      double before_ms, after_ms;
      if (sample % 2 == 0) {
        before_ms = measure(corpus, before, before_sum);
        after_ms = measure(corpus, after, after_sum);
      } else {
        after_ms = measure(corpus, after, after_sum);
        before_ms = measure(corpus, before, before_sum);
      }
      if (before_sum != after_sum) { std::abort(); }
      std::printf("%s sample=%d baseline_ms=%.3f optimized_ms=%.3f checksum=%llu\n",
          names[group], sample, before_ms, after_ms,
          static_cast<unsigned long long>(after_sum));
    }
  }
}
} // namespace

int main(int argc, char **argv)
{
  correctness();
  if (argc > 1 && 0 == std::strcmp(argv[1], "--bench")) { benchmark(); }
  return 0;
}
