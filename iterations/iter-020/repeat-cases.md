## Explicit local-repeat cases

| fixture | source span | expected | cut words | remainder kept | result |
|---|---|---|---:|---|---|
| test-10 | 87:19-30 user: repeated suffix before later clean sentence | cut | 11/11 | yes | PASS |
| test-10 | 23:0-3 user: truncated within-sentence restart | cut | 0/3 | yes | FAIL |
| test-10 | 19:18-28 user: repeated clause before later clean sentence | cut | 10/10 | yes | PASS |
| test-11 | 71:13-17 user: corrected grammatical perspective | cut | 0/4 | yes | FAIL |
| engleski25ljeto-listening-1 | 17:13-22 discovered: adjacent repeated suffix | cut | 9/9 | yes | PASS |
| engleski25ljeto-listening-2 | 18:4-12 discovered: adjacent repeated suffix | cut | 8/8 | yes | PASS |
| engleski25ljeto-listening-2 | 19:9-12 discovered: adjacent repeated suffix | cut | 3/3 | yes | PASS |
| test-1 | 20:24-30 discovered: adjacent repeated suffix | cut | 6/6 | yes | PASS |
| test-13 | 45:4-19 discovered: adjacent repeated suffix | cut | 15/15 | yes | PASS |
| test-40 | 39:0-4 discovered: adjacent repeated suffix | cut | 4/4 | yes | PASS |
| test-41 | 51:19-25 discovered: adjacent repeated suffix | cut | 6/6 | yes | PASS |
| test-9 | 26:0-3 discovered: adjacent repeated suffix | cut | 3/3 | yes | PASS |
| engleski25ljeto-esej | 40:3-12 user: keep early prefix and remove abandoned first completion | cut | 9/9 | yes | PASS |
| engleski25ljeto-esej | 43:0-7 user: remove doubled start before final completion | cut | 7/7 | yes | PASS |
| engleski25ljeto-listening-1 | 16:6-20 user: remove abandoned explanation before corrected continuation | cut | 0/14 | yes | FAIL |
| engleski25ljeto-listening-1 | 148:0-21 user: remove first take across an intervening false start | cut | 21/21 | yes | PASS |
| engleski25ljeto-listening-1 | 108:11-15 control: quoted phrase used once in the explanation | keep | 0/4 | yes | PASS |
| engleski25ljeto-listening-2 | 160:2-4 control: definition by intentional repetition | keep | 0/2 | yes | PASS |
| engleski25ljeto-reading-1 | 183:9-12 control: grammatical phrase comparison | keep | 0/3 | yes | PASS |
| engleski25ljeto-reading-1 | 305:3-7 control: translation followed by expansion | keep | 0/4 | yes | PASS |
| engleski25ljeto-reading-5 | 164:0-3 control: deliberate synonym pair | keep | 0/3 | yes | PASS |
| engleski25ljeto-reading-5 | 221:1-4 control: English synonym pair | keep | 0/3 | yes | PASS |
| test-11 | 22:16-18 control: repeated grammatical construction | keep | 0/2 | yes | PASS |
| engleski25ljeto-esej | 20:12-14 control: vocabulary definition | keep | 0/2 | yes | PASS |
| engleski25ljeto-esej | 150:11-13 control: intentional structural emphasis | keep | 0/2 | yes | PASS |
| engleski25ljeto-reading-1 | 353:4-7 control: translation equivalents | keep | 0/3 | yes | PASS |
| engleski25ljeto-listening-1 | 174:0-7 bilingual: Croatian translation after English source | keep | 7/7 | yes | FAIL |
| engleski25ljeto-listening-2 | 14:0-14 bilingual: English source before corrected Croatian explanation | keep | 14/14 | no | FAIL |
| engleski25ljeto-reading-1 | 109:0-15 bilingual: Croatian framing with English teaching phrase | keep | 0/15 | yes | PASS |
| engleski25ljeto-reading-1 | 157:0-9 bilingual: English phrase explained in Croatian | keep | 0/9 | yes | PASS |
| engleski25ljeto-reading-5 | 64:0-5 bilingual: Croatian translation framing after English source | keep | 5/5 | no | FAIL |
| engleski25ljeto-listening-1 | 18:0-9 chain control: keep later standalone English sentence | keep | 0/9 | yes | PASS |
| engleski25ljeto-listening-1 | 150:0-19 chain control: keep final complete take | keep | 0/19 | yes | PASS |

Positive repeat cases: 13/16
Intentional-repeat controls: 14/17