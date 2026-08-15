# I gave five graph databases the same tiny free-tier box. Here's what actually happened.

If you've ever picked a database off a benchmark blog post, you've probably
noticed the trick: the winning database always got the biggest instance,
the warmest cache, and the friendliest dataset. That's not a benchmark,
it's an ad.

So here's the setup I used instead: **one dataset, one set of queries, and
every database squeezed into the same tiny box** — 0.5 vCPU, 256MB of RAM,
1GB of disk. That's not a random number; it's what [CognoDB
Cloud](https://console.cognodb.com)'s free tier actually gives you, and I
held four other graph databases to the exact same limit rather than letting
anyone bring more hardware to the fight.

The dataset: a 126,297-node, 200,000-edge sample of the SNAP `soc-Pokec`
social graph. The databases: CognoDB Cloud (the platform in question),
Neo4j AuraDB Free (the closest real apples-to-apples — same protocol, same
driver, different cloud), and three self-hosted references running in
Docker under the identical resource cap — Neo4j Community, Memgraph, and
ArangoDB. Full methodology, all the raw numbers, and the code that produced
them are in [the repo](.) — this post is the readable version.

## The one-sentence result

**Where a database runs matters more than what it is.**

Every self-hosted platform answered a one-hop "who are my friend's
friends" query in under 3 milliseconds. Both managed clouds took over a
quarter of a second — 100 to 1,000 times slower — for the *exact same
query, over the exact same data*. That gap isn't a query-planner problem.
It's the cost of a network round trip to somebody else's datacenter,
showing up in every single measurement, every single time.

If you take one chart from this whole project, take this one:

| Platform | 1-hop p50 | What it's running on |
|---|---|---|
| Memgraph | 0.52 ms | Self-hosted, in your own container |
| ArangoDB | 1.75 ms | Self-hosted, in your own container |
| Neo4j Community | 2.49 ms | Self-hosted, in your own container |
| Neo4j AuraDB Free | 256.44 ms | Managed cloud, free tier |
| CognoDB Cloud | 909.81 ms | Managed cloud, free tier |

Same graph. Same query. Same client machine. The only thing that changed
between row three and row four is *where the database physically lives* —
and that alone is worth two and a half orders of magnitude.

## So is CognoDB just... slow?

Compared to running a database on your own laptop, sure — but that's not a
fair fight, and it's not the fight this benchmark is actually testing. The
fair fight is CognoDB against the one other platform in this list that's
also a real managed cloud on a free tier, speaking the exact same
Bolt/Cypher protocol, through the exact same official Neo4j driver: **Neo4j
AuraDB Free.**

And there, CognoDB loses consistently — not occasionally, not on one metric,
but by a steady 3–4× across *every* workload measured:

| Workload | CognoDB p50 | Aura p50 | Ratio |
|---|---|---|---|
| 1-hop traversal | 909.81 ms | 256.44 ms | 3.5× |
| Point lookup | 881.33 ms | 259.61 ms | 3.4× |
| Aggregation (count) | 859.08 ms | 256.70 ms | 3.3× |
| Ingest (nodes/sec) | 737/sec | 3,124/sec | 4.2× slower |

That consistency is itself the interesting finding. If CognoDB were just
occasionally flaky, you'd expect the ratio to bounce around. Instead it
holds steady across reads, writes, and aggregations — which points toward
something structural: maybe CognoDB's free-tier region sits farther from
wherever this benchmark ran, maybe it provisions less real compute behind
its "0.5 vCPU" than Aura does behind its own. I didn't measure raw network
round-trip-time to each endpoint separately from query time, so I can't
fully separate "far away" from "actually slower" — that's the single
biggest thing I'd add with another 48 hours, and I've said so plainly in
the repo rather than pretending the number speaks for itself.

CognoDB's connections were also noticeably less stable than Aura's — Bolt
connections dropped mid-query at roughly a 1-in-20 rate over the course of
this project, reproduced across multiple fresh instances, which is part of
why CognoDB's p95 numbers above are the worst in every table. The benchmark
code retries through this automatically (that's what a production client
should do), so the numbers you see are real end-to-end latency *including*
that retry cost — not a cherry-picked best case.

## The self-hosted three tell a different story

Take the managed clouds out of the picture and something more interesting
shows up: **the three self-hosted databases, under the identical 256MB
cap, don't all handle that cap the same way.**

Memgraph is fully in-memory, and it *shows* — sub-millisecond reads across
the board, and by far the best sustained write throughput under load
(2,117 queries/second with 40 concurrent clients hammering it, versus
1,614–2,843 for the field). But it paid for that speed with almost no
margin: while loading the 326,000-row dataset, Memgraph repeatedly hit
its own internal memory ceiling — logged, retried-through, and eventually
successful, but sitting right at ~200MB out of a 256MB cap. A bigger
dataset would likely have failed outright instead of retrying through it.

Neo4j Community told the opposite story. It's fast at low concurrency
(189 qps with a single client — actually the highest single-client number
in the whole benchmark) but **collapsed** once 10 or 40 clients started
writing concurrently: 10 failed transactions out of a few hundred at
concurrency 10, and effectively zero successful throughput at concurrency
40. That's not a driver bug — it's write-lock contention on a small graph,
inside a container that genuinely doesn't have the memory headroom to
absorb the queueing. It's a resource story, not a software-quality one, and
it's exactly the kind of thing a "0.5 vCPU / 256MB" free tier is supposed
to expose.

ArangoDB, interestingly, didn't make either of those tradeoffs sharply. It
was the fastest platform to *load* data (14,379 nodes/sec — nearly 20×
CognoDB's rate) and held solid throughput at every concurrency level
without a single error, all while still persisting to disk rather than
holding everything in memory the way Memgraph does. If there's an
underappreciated result in this whole project, it's that ArangoDB — the
one database here that *isn't* even speaking the same query language as
the rest — quietly turned in the most balanced performance of the five.

## What I'd tell someone actually choosing a database from this

Not "use X, skip Y" — the assignment brief is right that the point isn't
picking a winner. It's this: **decide what you're optimizing for before you
look at a single benchmark number**, because these five platforms didn't
just finish in a different order, they optimized for genuinely different
things:

- Need the lowest possible read latency and can run it yourself?
  Self-hosted, in-memory (Memgraph) wins by two orders of magnitude —
  if your dataset actually fits in RAM.
- Need to not think about infrastructure at all, and latency in the
  hundreds-of-milliseconds range is fine for your use case (background
  jobs, periodic batch queries, low-QPS internal tools)? A managed cloud
  is a reasonable, boring choice — and between the two tested here, **Aura
  measured faster and more stable than CognoDB** on this dataset, this
  hardware tier, this network path.
- Need to survive write-heavy concurrency on a genuinely small box?
  ArangoDB's balance and Memgraph's raw throughput both beat Neo4j
  Community's collapse under the same cap — worth knowing before you pick
  "the default choice" out of habit.

None of that is a verdict on any database's engineering quality in
general — it's a verdict on what happens when you put all five in the
smallest box a free tier will give you and measure honestly.

## The part most benchmarks skip

Every one of the platform-specific gotchas above — Memgraph's memory
ceiling, Neo4j Community's concurrency collapse, CognoDB's connection
flakiness — showed up because of something almost embarrassingly mundane:
I re-ran the loader against an already-populated database by accident,
more than once, using a non-idempotent `CREATE` instead of `MERGE`. Two
instances silently ballooned to 5–8× their intended size before I noticed.
The fix was straightforward (wipe and reload clean, verify counts before
timing anything), but the bug itself is still sitting in the code,
undocumented nowhere except the repo's own caveats section, because hiding
it wouldn't make the numbers more true — it would just make them look more
confident than they are.

That's the actual point of a benchmark like this: not "who wins," but
whether you can trust the number enough to make a real decision from it.
Every caveat above is in the repo's README precisely so you don't have to
take my word for any of this — the harness, the raw results, and the exact
retry logs are all there to check.

**[Full methodology, raw results, and reproducible code →](.)**
