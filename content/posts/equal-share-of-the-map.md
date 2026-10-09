---
title: In 2020 we gave every drone an equal share of the map. That was the mistake.
date: 2026-10-09
summary: I rebuilt a hackathon project six years later and benchmarked it against the original. Planning one route first and splitting it afterwards finished 41% sooner.
---

In 2020, my team built a drone route planner for a hackathon. The problem came from ISRO: given an area to map, a fleet of drones, their battery range, and the locations of charging stations, plan the routes so that the whole area is photographed in the shortest time.

The idea looks obviously fair. Divide the map into equal regions, one per drone. Plan a path through each region. Add recharging stops where the battery runs out.

Six years later I rebuilt it from scratch, and kept a faithful copy of the old approach to race against. The new planner finishes about 41% sooner. Most of that gain comes from undoing the very first decision we made.

The code is in [drone-coverage-planner](https://github.com/yash-bitla/drone-coverage-planner).

![Animated replay of a four-drone plan: coverage lanes over a city map, with a schedule chart below](/img/drone-demo.gif)

## What we are actually minimizing

The goal is **makespan**: the time until the last drone lands with every part of the area photographed.

That one word, *last*, is the whole problem. It does not matter how fast three drones finish if the fourth is still out. The rules that make this hard:

- Every flight starts and ends at a charging station, and must fit in one battery.
- A station charges one drone at a time. Everyone else waits on the ground.
- Buildings taller than the flight altitude must be flown around.

## The original plan, and why it loses

The 2020 version works in three steps: split the area evenly between the drones, build a path inside each region, then insert trips back to a charger wherever the battery would run out.

The flaw is in the first step. An even split balances **area**. The objective is **time**. Those are not the same thing.

Picture two regions of the same size. One sits next to a charging station. The other is on the far side of the map. The far drone spends a large part of every battery just commuting, so it needs more flights, more recharges, and more time. It finishes last, and the last drone sets the score. An equal share of the map is an unequal share of the work.

There were smaller problems too. Recharging was bolted on after the paths were fixed, so it could never influence them. The path-building method turns at almost every cell, and a drone has to slow down to turn. And nothing modeled the queue at a charger, so two drones could plan to charge at the same pad at the same time.

## The rebuild: route first, split second

The new planner turns the order around. It is an old idea from vehicle routing, usually called route-first, cluster-second.

1. **Route.** Ignore the drones and the batteries. Plan one long tour that covers the whole area in straight lanes, like mowing a lawn. Rotate the lanes to run along the narrow direction of the area, which gives the fewest lanes and so the fewest U-turns.
2. **Split.** Cut that tour into flights that each fit in one battery, including the trip from a station and back. A dynamic program finds the cheapest set of cuts. For a given tour this is provably the best split, and the tests check it against brute force.
3. **Schedule.** Hand the flights to the drones, longest first. Each drone lands at the station where its charge will finish soonest, counting the queue already there.

Nothing here assigns a drone to a place. A drone just takes the next flight. If one part of the map is expensive to reach, that cost is shared across the fleet instead of landing on whoever was unlucky enough to be given that corner.

Underneath all of it is one router: a visibility graph over the corners of the obstacles, which gives exact shortest paths around buildings. Every algorithm, old and new, gets its distances from the same router, so the comparison is fair.

## The race

I generated 30 random areas: irregular polygons with 8 to 15 sides, some with holes, with 1 to 4 stations and 2 to 8 drones. Each one runs with and without obstacles, so 60 instances.

| Planner | Mean makespan | Against the 2020 approach | Turns |
|---|---:|---:|---:|
| 2020 approach (even split) | 416 min | | 599 |
| New planner (route, split, schedule) | 256 min | -42% | 134 |

Those are the numbers without obstacles. With obstacles it is 413 minutes against 256, which is 41% less. The new planner won on all 60 instances, and it plans each one in about a second.

A note on fairness, because it is easy to win a race against your own past self. The 2020 baseline here is a re-implementation with its bugs fixed. The original crashed in some cases and measured distance in degrees. Beating broken code proves nothing, so I fixed it first and then raced it.

## The experiment that changed my mind

I assumed the win came from the path shape. Straight lanes have far fewer turns than the old method, 134 against 599, and turns cost time. So I ran a test: keep the even split from 2020, but give each drone my nice straight lanes inside its region.

It had half the turns of the original. It was **no faster**. It landed within about one and a half percent of the original, a little better on one set of instances and a little worse on the other.

That result is the reason this post has the title it does. Better paths inside a bad division of work do not help. The gain comes from dividing the work by time instead of by area.

I also removed the other ideas one at a time, to see what each was worth:

| Remove this | Percentage points of the gain lost |
|---|---:|
| The optimal split (use a greedy one) | about 5 points |
| Rotating the lanes to the narrow direction | about 4 to 5 points |
| Searching over the flight length | about 2 points |

Even the weakest version was still about 36% faster than the 2020 approach. The details matter, but the structure matters most.

## The part I trust most is not the planner

It is the validator.

A plan from any of these algorithms is a long list of timed waypoints, and a planner can produce a confident, wrong one. So a separate checker, which shares no logic with the planners, verifies every plan: every cell covered, every flight inside its battery range, every flight starting and ending at a station, no path through a building, no two drones on one charging pad at once.

All 360 plans in the benchmark pass. Without that check I would not believe my own table. A faster plan is easy to produce if it is allowed to cheat.

## What it does not prove

- **It is not optimal, and I cannot say how close it is.** I compute a lower bound on the makespan, and the new planner lands about 100% above it. But the bound is loose: it ignores turns and most of the flying to and from stations. A big gap here does not mean the plan is bad. It means my bound is weak.
- **The areas are synthetic.** They are random polygons, not survey sites.
- **The physics is simple.** No wind, and drones are assumed to be separated by altitude, so they never collide.
- **It slows down with many obstacles.** The router compares every pair of obstacle corners. A dense building layer needs simplifying first.

## What I took from this

The 2020 version was not lazy. Splitting the map evenly is a reasonable thing to do, and there is a well-known algorithm for it. The mistake was earlier and quieter: we picked the first step before we had looked hard at what we were minimizing. We balanced the thing that was easy to balance.

Rebuilding something you made years ago is a strange exercise. You get to see exactly which of your old instincts were wrong, with a number attached.
