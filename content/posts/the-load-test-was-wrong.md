---
title: My load test said the service broke at 350 requests a second. The load test was wrong.
date: 2026-10-09
summary: I built an event search service on top of a rate-limited API and measured every part. Three of my first designs were wrong, and the benchmarks are how I found out.
---

Most backend services depend on someone else's API, and that API has rules. You get a fixed number of calls a day. You can only call so fast. Sometimes it does not answer at all.

I wanted to build a service that lives inside those rules and to measure how well it does. The service answers one question: which events are near this location in this date range? The events come from an upstream API with a quota of 5,000 calls a day and a limit of 5 calls a second. Those are the documented limits of the Ticketmaster Discovery API.

I did not use the real API. I wrote a local copy of it with the same limits, the same response headers, and the same error bodies. That gave me two things. Anyone can run every benchmark without an API key. And I can make the upstream fail on command, which the real one will not do for me.

The code and every number in this post are in [event-discovery-service](https://github.com/yash-bitla/event-discovery-service).

I measured every part, and the measurements kept correcting me. The one in the title came last: my first load test reported a limit of about 350 requests a second, and that limit belonged to the test, not to the service. That story is near the end. The sections before it are the other things I got wrong on the way there.

## The quota is smaller than it looks

The service keeps events fresh for 30 cities. One refresh of all 30 costs about 550 calls, because results come in pages. Refreshing everything every hour would cost 550 × 24 = 13,200 calls a day. I have 5,000.

So the ingestion worker has a budget. At the start of each hourly cycle it takes the calls that are left and spreads them over the time until the quota resets. On a fresh day that is 4,500 × 3,600 ÷ 86,400 = 187 calls for the first hour. I keep 500 calls in reserve. A planner then picks the cities with the best value per call, where value is the city's weight times how stale its data is.

I simulated one day and compared three policies.

| Policy | Calls accepted | Calls rejected | Mean staleness |
|---|---:|---:|---:|
| Refresh everything every hour | 5,000 | 15 | 5.44 h |
| Refresh everything every 3 hours | 4,351 | 0 | 1.52 h |
| Quota budget | 4,499 | 0 | 1.59 h |

The hourly policy burns the whole quota in the first ten hours and then sits blind until midnight.

The second row is the honest part. A fixed 3-hour interval does as well as my budget, and slightly better. The budget did not win at this quota. What it buys is that nobody has to work out "3 hours" by hand. When I cut the quota in half, the fixed interval started getting rejected and its staleness went to 4.43 hours. The budget adjusted by itself and reached 3.26.

This benchmark also caught a bug. My first planner skipped any city that cost more than one cycle's allowance. At the smaller quota, one large city went 14 hours without a refresh, because it never fit. The fix was a few lines. I would not have found it by reading the code.

## One failed call in five nearly stops everything

Next I made the upstream fail one call in five, for the whole day.

| Client | Successful refreshes | Failed refreshes | Mean staleness |
|---|---:|---:|---:|
| No retry | 59 | 659 | 10.16 h |
| Retry, up to 4 attempts | 205 | 5 | 2.07 h |

I expected retries to help. I did not expect the version without them to be this bad. The reason is pages. A city needs about 17 calls, and one failed call fails the whole refresh. The chance that 17 calls in a row all succeed at an 80% success rate is 0.8^17, which is 2.3%.

Retries go through the same budget as every other call. That detail matters: a retry loop that ignores the quota is how a bad hour for the upstream becomes a bad day for you.

## The circuit breaker did less than I thought

A circuit breaker stops calling an upstream that keeps failing, and sends one probe now and then to see if it is back. The usual pitch is that it saves you from wasting calls.

I simulated a two-hour outage and counted.

| Client | Failed calls | Time to recover |
|---|---:|---:|
| Retry only | 84 | 33.3 min |
| Retry + circuit breaker | 24 | 3.3 min |

The breaker saved 60 calls. Out of 5,000, that is close to nothing. With an hourly cycle there are not many calls to waste in the first place. The staleness for the day was also the same, because no client can refresh during an outage.

What the breaker did improve is recovery. Without it, ingestion finds out the upstream is back at the next hourly cycle, 33 minutes later on average. With it, the next probe succeeds within five minutes and ingestion starts again at once. So the breaker was worth having, for a different reason than the one I built it for.

## One index, not two

Events go into PostgreSQL with PostGIS. Every search has two conditions: within some distance of a point, and within some range of time. I started with a spatial index on the location, which is the obvious choice. Then I measured it against the alternatives on a million events.

| Indexes | P50 | P95 |
|---|---:|---:|
| None | 178.35 ms | 209.20 ms |
| Location only | 26.04 ms | 73.90 ms |
| Location and time, two indexes | 5.91 ms | 22.66 ms |
| Location and time, one combined index | 2.57 ms | 17.06 ms |

My first design was the second row. The combined index is ten times faster at the median, so the schema uses that now. In a city with many events, "near this point" still matches a lot of rows, and the time condition is what cuts them down.

## The cache, and the bug in my load test

The API reads only the database, never the upstream. That is why an upstream outage cannot reach the people searching. I checked it under load: with the upstream down for 30 seconds and 200 requests a second coming in, clients saw zero errors and no change in latency.

Then I added a Redis cache with a 60-second lifetime and ran a load test.

| Requests per second | Cache | Served per second | P95 | Errors |
|---:|---|---:|---:|---:|
| 400 | no | 400 | 23.9 ms | 0 |
| 800 | no | 595 | 3,573 ms | 12,314 |
| 800 | yes | 800 | 10.5 ms | 0 |
| 1,200 | yes | 1,200 | 11.5 ms | 0 |

Without the cache the service tops out near 600 requests a second. With it, 1,200 was fine, and that was the highest rate I tested.

Getting to this table took two wrong turns.

First, my load generator was the bottleneck. The early runs showed the service falling over at about 350 requests a second, cache or no cache. I added more API processes and the number did not move at all. That was the clue: if adding capacity changes nothing, you are not measuring the thing you added capacity to. One Python process could not send requests fast enough, and I was reading its delay as the server's latency. The generator now runs as four processes and reports how late it sent each request, so a bad row is visible as a bad row.

Second, the Redis client retries three times by default. I had set a 0.1-second timeout so that a Redis failure would fall through to the database quickly. With Redis down, a request took more than two seconds anyway. A slow test is the only reason I noticed.

## What I would tell someone building this

- **Put every call through one budget**, retries and probes included.
- **Retries matter more when work comes in pages.** A small error rate per call becomes a large failure rate per job.
- **Know what your circuit breaker is for.** Mine barely saved quota. It made recovery ten times faster.
- **Index for the whole query**, not for the first condition you think of.
- **Distrust a benchmark that does not react.** When more capacity changes nothing, check the tool.

## Limits

Everything ran on one laptop: the API, the database, Redis, and the load generator. The ingestion results use simulated time and synthetic events. The upstream is my copy of the documented limits, and I did not run against the real API. The cache hit rate (about 85%) comes from a workload I made up, where most searches repeat, and a different workload would give a different number. Ratios should hold up better than absolute times.

Everything here is reproducible from the [repository](https://github.com/yash-bitla/event-discovery-service).
