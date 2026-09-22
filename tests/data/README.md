# Committed regression data

`worker_contract/` contains the six existing example request/snapshot JSON files
used by worker tests. They were previously ignored under `tests/fixtures/`, so a
fresh checkout of `f779947` could not run those tests. The examples contain fake
Drive identities, object keys and checksums, with no credentials.

`local_corrections/` retains the five complete real transcript inputs already
required by deterministic correction regressions (including negative controls).
They are copied read-only from the original checkout's ignored fixtures. Only
JSON whitespace is compacted to one sentence per line; every value, timestamp,
word, sentence index and metadata field is preserved. No source audio/video,
rendered output, EDL promotion or local corpus regeneration is needed.

Source-file SHA-256 before whitespace normalization:

| Transcript | SHA-256 |
| --- | --- |
| `engleski25ljeto-esej-raw.transcript.json` | `191f48954ee821e6c213f7d3842fcaaac898982527116d53aab03bfc91abddf2` |
| `engleski25ljeto-listening-1-raw.transcript.json` | `2aff9222ec0ee529061db50a2eba0a6319e88094b32eeacf553858e7ee28e8f5` |
| `test-44-raw.transcript.json` | `2a03f6e5d05e7070ca1297d4a6595fa9bf25f15818a2f0d14df3babe60d28e09` |
| `test-45-raw.transcript.json` | `9ca19ee622f7fa782ea6e53911c0267e8619e514624864b6955226b419859e86` |
| `test-6-raw.transcript.json` | `d79c6bb9687e411913c2425e462616c6d4ccafefc9145579d55b6170fc09f090` |
