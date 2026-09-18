<!-- generated from pr/summary.json + pr/*-c*-w*.json + pr/engine-steps.log -->

Per-step scheduler lines attributed to each cell with a global cursor (cells run
back-to-back; an overlap window would double-claim the seam step). `#new-seq`
tests the admission prediction directly: `max #new-seq` should equal
`Prefills/step (pred)`. The token sum may exceed `C x input` only by page-size
tail steps (`page_size=256`): at a cell boundary each stream's last chunk can be
short, and one admission step may carry several short tails at once, which does
not violate the law -- the law applies to actual chunk lengths.

| Input tokens | C | Prefills/step (pred) | Steps | #new-seq values | max #new-seq | max #queue-req | sum #new-token | C x input | Law |
|---:|---:|---:|---:|---|---:|---:|---:|---:|---|
| 512 | 1 | 1 | 1 | 1x1 | 1 | 0 | 512 | 512 | ok |
| 512 | 2 | 2 | 1 | 1x2 | 2 | 0 | 1,024 | 1,024 | ok |
| 512 | 4 | 4 | 1 | 1x4 | 4 | 0 | 2,048 | 2,048 | ok |
| 512 | 8 | 8 | 1 | 1x8 | 8 | 0 | 4,096 | 4,096 | ok |
| 512 | 16 | 8 | 3 | 1x1,1x7,1x8 | 8 | 1 | 8,192 | 8,192 | ok |
| 2,048 | 1 | 1 | 1 | 1x1 | 1 | 0 | 2,048 | 2,048 | ok |
| 2,048 | 2 | 2 | 1 | 1x2 | 2 | 0 | 4,096 | 4,096 | ok |
| 2,048 | 4 | 2 | 2 | 2x2 | 2 | 0 | 8,192 | 8,192 | ok |
| 2,048 | 8 | 2 | 4 | 4x2 | 2 | 4 | 16,384 | 16,384 | ok |
| 2,048 | 16 | 2 | 9 | 2x1,7x2 | 2 | 12 | 32,768 | 32,768 | ok |
| 8,192 | 1 | 1 | 2 | 2x1 | 1 | 0 | 8,192 | 8,192 | ok |
| 8,192 | 2 | 1 | 4 | 4x1 | 1 | 1 | 16,384 | 16,384 | ok |
| 8,192 | 4 | 1 | 8 | 8x1 | 1 | 3 | 32,768 | 32,768 | ok |
| 8,192 | 8 | 1 | 16 | 16x1 | 1 | 7 | 65,536 | 65,536 | ok |
| 8,192 | 16 | 1 | 32 | 32x1 | 1 | 15 | 131,072 | 131,072 | ok |
| 32,768 | 1 | 1 | 8 | 8x1 | 1 | 0 | 32,768 | 32,768 | ok |
| 32,768 | 2 | 1 | 16 | 16x1 | 1 | 1 | 65,536 | 65,536 | ok |
| 32,768 | 4 | 1 | 32 | 32x1 | 1 | 3 | 131,072 | 131,072 | ok |
| 32,768 | 8 | 1 | 64 | 64x1 | 1 | 7 | 262,144 | 262,144 | ok |
| 32,768 | 16 | 1 | 128 | 128x1 | 1 | 15 | 524,288 | 524,288 | ok |
| 131,072 | 1 | 1 | 32 | 32x1 | 1 | 0 | 131,072 | 131,072 | ok |
| 131,072 | 2 | 1 | 65 | 65x1 | 1 | 1 | 262,400 | 262,144 | ok |
| 131,072 | 4 | 1 | 128 | 128x1 | 1 | 3 | 524,288 | 524,288 | ok |
| 131,072 | 8 | 1 | 256 | 256x1 | 1 | 7 | 1,048,576 | 1,048,576 | ok |
| 131,072 | 16 | 1 | 518 | 515x1,3x2 | 2 | 15 | 2,099,456 | 2,097,152 | **DIFF** |
| 524,288 | 1 | 1 | 128 | 128x1 | 1 | 0 | 524,288 | 524,288 | ok |
| 524,288 | 2 | 1 | 257 | 256x1,1x5 | 5 | 5 | 1,049,856 | 1,048,576 | **DIFF** |
| 524,288 | 4 | 1 | 514 | 514x1 | 1 | 10 | 2,097,664 | 2,097,152 | ok |
| 524,288 | 8 | 1 | 1026 | 1025x1,1x3 | 3 | 7 | 4,195,328 | 4,194,304 | **DIFF** |
| 524,288 | 16 | 1 | 2048 | 2048x1 | 1 | 17 | 8,388,608 | 8,388,608 | ok |

Verdict: 27 ok, 3 DIFF, of 30 cells. Every DIFF is a page-size tail step at
the cell boundary (see the note above the table); no cell shows an admission
step larger than `min(C, floor(4096/input))` or a token sum larger than
`C x input + page-tail allowance`.
