// Copyright (c) 2025 OceanBase.
// Licensed under the Apache License, Version 2.0.
// Compare the real ObString implementation with the UTF8MB4_BIN handler.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <random>
#include "lib/string/ob_string.h"
#include "lib/charset/ob_ctype.h"

int main()
{
  std::mt19937 rng(2701);
  std::array<char, 6> left{};
  std::array<char, 6> right{};
  long cases = 0;
  auto check = [&](const char *l, int ln, const char *r, int rn) {
    const int expected = ob_strnncoll_mb_bin(nullptr,
        reinterpret_cast<const unsigned char *>(l), ln,
        reinterpret_cast<const unsigned char *>(r), rn, false);
    const int actual = oceanbase::common::ObString(ln, l).compare(
        oceanbase::common::ObString(rn, r));
    if ((actual < 0) != (expected < 0) || (actual > 0) != (expected > 0)) {
      std::fprintf(stderr, "binary comparison differs: lengths %d/%d\n", ln, rn);
      std::abort();
    }
    ++cases;
  };
  for (int a = 0; a < 256; ++a) {
    for (int b = 0; b < 256; ++b) {
      left[0] = static_cast<char>(a);
      right[0] = static_cast<char>(b);
      check(left.data(), 1, right.data(), 1);
    }
  }
  for (int i = 0; i < 100000; ++i) {
    for (int j = 0; j < 6; ++j) {
      left[j] = static_cast<char>(rng());
      right[j] = static_cast<char>(rng());
    }
    const int ln = rng() % 7;
    const int rn = rng() % 7;
    check(left.data(), ln, right.data(), rn);
    check(left.data(), ln, left.data(), rn); // shared pointer and prefixes
    check(left.data(), ln, left.data(), ln); // equality including zero length
  }
  std::printf("PASS: %ld real binary-collation comparisons\n", cases);
}
