# Changelog

## 1.1.0

- Integrated the complete `bible-io-references` 1.1 public API.
- Added the versioned schema-v1 content contract, lossless annotations,
  translation metadata, explicit edition ordering, strict/permissive
  validation, and path-aware data errors.
- Added construction from paths, strings, UTF-8 bytes, decoded mappings, and
  direct model values, including synchronous/asynchronous helpers and load
  progress values.
- Added declared-number lookup for sparse content, location-based navigation,
  edition-aware verse keys, custom-canon ranges, rich-passage resolution, and
  canonical JSON round-tripping.
- Added Unicode-normalized exact/all/any and fuzzy search, scoped pagination,
  display-ready hits and snippets, and eager/lazy/disabled index policies.
- Added immutable content and annotation trees, defensive model collections,
  copy helpers, statistics, performance diagnostics, source metadata, and
  catalogs.
- Fixed semantic duplicate-book handling, legacy alias parsing, non-canonical
  input ordering, duplicate JSON members, malformed Unicode/data error
  leakage, and lossy metadata loading.
- Aligned inclusive single-verse edition ranges, contiguous chapter-passage
  validation, checked source/metadata diagnostics, non-blocking async file
  reads, and scalar load progress with the current Rust and Dart contracts.
- Added Rust/Dart parity, adversarial validation, multilingual, concurrency,
  full-fixture integrity, and grapheme-boundary tests with a branch-aware 90%
  coverage gate.
- Corrected package license metadata and excluded tests, caches, and build
  artifacts from source distributions.
