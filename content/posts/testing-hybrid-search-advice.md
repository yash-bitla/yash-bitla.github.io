---
title: I tested the standard hybrid search advice. About half of it held.
date: 2026-10-08
summary: I built a search engine in stages and measured each one on two datasets. Rank fusion did not beat dense retrieval, and neither reranker was worth its cost.
---

If you ask how to build good search for a RAG system, you get the same recipe almost everywhere: combine keyword search with vector search, fuse the two with reciprocal rank fusion, then put a reranker on top.

I wanted to know how much each step is worth. So I built the pipeline one stage at a time and measured every stage against the one before it. On the two datasets I used, about half of the recipe held up.

The code and every number in this post are in [hybrid-retrieval-engine](https://github.com/yash-bitla/hybrid-retrieval-engine).

## The setup

I used two datasets from the [BEIR](https://github.com/beir-cellar/beir) benchmark:

- **SciFact**: 5,183 paper abstracts and 300 scientific claims to match against them.
- **FiQA**: 57,638 finance forum answers and 648 questions.

The quality metric is nDCG@10. It runs from 0 to 1, and it is higher when the right documents are nearer the top of the first ten results.

I set three rules before I looked at any result:

1. **Tune on training queries, test once.** Anything with a knob was tuned on the training split. The test queries were used one time, for the final tables.
2. **Compare with a paired test.** With 300 queries, the confidence interval on nDCG@10 is about ±0.045. Two retrievers that differ by 0.02 have overlapping intervals, but they answer the same queries, so I bootstrap the per-query difference instead. If that interval excludes zero, the difference is real.
3. **Check against published numbers.** My BM25 scores 0.660 on SciFact and 0.236 on FiQA. The BEIR paper reports 0.665 and 0.236. If those had not matched, nothing after them would mean much.

## Dense retrieval beat BM25. No surprise.

BM25 is my own implementation: an inverted index that matches words. Dense retrieval uses a small embedding model (`bge-small-en-v1.5`) and matches by meaning.

| Retriever | SciFact nDCG@10 | FiQA nDCG@10 | Latency (P50) |
|---|---:|---:|---:|
| BM25 | 0.660 | 0.236 | under 1 ms |
| Dense | 0.713 | 0.403 | 7 to 9 ms |

Dense is better on both, by 0.052 and 0.168, and both differences are significant. It is also slower, and almost all of that time is the model turning the query into a vector.

So far the recipe holds.

## Rank fusion did not beat dense retrieval

This is the step everyone recommends. Reciprocal rank fusion (RRF) merges two rankings by position, so you do not need to make their scores comparable. It is simple and it needs no tuning.

It also did not help.

| Compared with dense alone | SciFact | FiQA |
|---|---|---|
| Hybrid with RRF | -0.009 (not significant) | **-0.054 (significant)** |
| Hybrid with a tuned weight | +0.018 (significant) | +0.009 (significant) |

On SciFact, RRF was no better than dense. On FiQA it was clearly worse.

The reason is that RRF gives both retrievers an equal vote. On FiQA, BM25 is far behind dense (0.236 against 0.403), so half of the vote comes from a much weaker system, and it pulls good results down.

A weighted fusion fixes this. I normalized each retriever's scores, then tried 11 weights on the training queries. The best mix was 70% dense on SciFact and 80% dense on FiQA. That version beat dense on both datasets.

But look at the size of the win: 0.018 and 0.009. It is real, and it is small. Hybrid search was not the big jump I expected. What it did improve on SciFact was recall: the share of relevant documents in the top 100 went from 94.2% to 96.8%.

## Neither reranker was worth its cost

A reranker is a slower model that reads the query and each candidate together and rescores them. I tested two cross-encoders on SciFact, a small one (23M parameters) and a larger one (278M), each at four depths: rerank the top 10, 20, 50, or 100.

![nDCG@10 against P95 latency for two rerankers at four depths. Both lines fall as depth grows.](/img/scifact-rerank.png)

The dashed line is the pipeline with no reranker: 0.731 nDCG@10. The chart plots P95 latency, and the table below gives the median.

| Reranker | Depth | nDCG@10 | Change | Latency (P50) |
|---|---:|---:|---|---:|
| None | | 0.731 | | 11 ms |
| Small | 10 | 0.711 | -0.020 | 62 ms |
| Small | 100 | 0.690 | -0.041 (significant) | 443 ms |
| Large | 10 | 0.734 | +0.003 (not significant) | 312 ms |
| Large | 100 | 0.710 | -0.021 | 2,635 ms |

The small model made the ranking worse. The large one never moved it by a significant amount, and its best result cost 312 ms against 11 ms. That is 28 times the latency for nothing I could measure.

The part that surprised me most is the slope. Both lines go **down** as the reranker sees more candidates. The first stage already had 96.8% of the relevant documents in its top 100, so better documents were there to promote. The rerankers promoted the wrong ones.

My best guess is domain mismatch. Both rerankers are general-purpose models, and SciFact queries are scientific claims. I did not test that explanation, and I only ran the rerankers on one dataset, so treat this as one data point and not a law. It is still a useful one: a reranker is a hypothesis to test on your own data, not a default.

## The two speed-ups, and why only one mattered

**Pruning BM25.** A plain BM25 search reads every index entry for every query word. MaxScore, an algorithm from 1995, skips documents that cannot reach the top ten, and it returns exactly the same results.

| Documents | Plain (P50) | MaxScore (P50) | Speed-up |
|---:|---:|---:|---:|
| 5,183 | 0.10 ms | 0.04 ms | 2.5x |
| 57,638 | 0.76 ms | 0.26 ms | 2.9x |
| 522,931 | 4.30 ms | 0.45 ms | 9.6x |

The gain grows with the corpus, and on the largest one MaxScore read only 5% of the index entries. I also ran the same compiled code with pruning switched off, and it was *slower* than the plain NumPy version. So the win comes from the algorithm and not from the compiler.

**Approximate vector search.** HNSW is the index behind most vector databases. On FiQA it found 99.0% of the exact results and was 4.5 times faster than checking every vector (0.29 ms against 1.33 ms).

It also made almost no difference. Encoding the query takes 6.46 ms. So a full query went from 6.46 + 1.33 = 7.79 ms to 6.46 + 0.29 = 6.75 ms, which is 13% faster, in exchange for a longer build, more memory, and a small loss in recall. At 57,000 documents, a matrix multiplication is fine. By my estimate the index starts to matter somewhere near 280,000 documents, where exact search would cost as much as the encoder.

## What I would tell someone building search

On these two datasets:

- **Start with dense retrieval.** It was the largest single gain.
- **Do not assume fusion helps.** RRF with a weak partner hurt. If you fuse, tune the weight on held-out queries.
- **Measure a reranker before you ship it.** Mine cost 28 to 240 times the latency and gave nothing back.
- **Find your real bottleneck first.** I could have spent a week on a vector index to save one millisecond out of eight.

And two things about method that mattered more than any single result:

- **Use a paired test.** Without it, every comparison in this post would have read as "the intervals overlap, so who knows".
- **Report the result you did not expect.** I started this project expecting to show that hybrid search with a reranker wins. The honest version is more useful.

## Limits

Two datasets, one embedding model, two rerankers, and one laptop. The reranker result is from SciFact only. Latency ratios should transfer to other hardware better than the absolute numbers do. I would not be surprised if a domain-tuned reranker, or a different corpus, changed some of these conclusions, and that is the point: these are things to measure, not things to assume.

Everything here is reproducible from the [repository](https://github.com/yash-bitla/hybrid-retrieval-engine). If you run it on your own data and get a different answer, I would like to hear about it.
