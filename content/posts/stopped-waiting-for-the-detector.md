---
title: My object detector was too slow for live video. So I stopped waiting for it.
date: 2026-10-09
summary: A tracker that waits for a slow detector shows boxes that are 100 ms late. Running the detector in the background, with optical flow in between, cut that to 5 ms and scored higher.
---

A camera at 30 frames a second gives you a new frame every 33 ms. The object detector I wanted to use takes about 80 ms on my laptop CPU. So by the time it finishes one frame, the camera has moved on by two more.

Most tracking code ignores this. It runs the detector on every frame and assumes the detector keeps up. On recorded video that is fine, because the video waits. On a live stream, the world does not wait, and the boxes you draw are for where people were, not where they are.

I built [leantrack](https://github.com/yash-bitla/leantrack) to answer one question: if the detector is a limited resource, when should it run, and what does each choice cost in accuracy?

![Two views of the same street. On the left the boxes trail behind the people. On the right they stay on them.](/img/leantrack-demo.gif)

On the left, the loop waits for the detector, so the boxes are behind the people. On the right, the detector runs in the background and the boxes stay on them. Same detector, same video.

## The setup

A tracker does two jobs. The **detector** finds people in one frame. The **tracker** connects those detections across frames, so that person 7 stays person 7.

- **Data:** the MOT17 training set, seven street sequences.
- **Detector:** YOLOX-s through ONNX Runtime, on the CPU of an Apple M3 Pro.
- **Metric:** HOTA, which runs from 0 to 100 and rewards both finding people and keeping their identities.

Two cautions before any numbers. First, my detector has general-purpose weights and was never trained on this dataset, so the absolute scores are low. The comparisons between configurations are the result. Second, I wrote the tracker core myself, so I checked it against a known implementation first: on the same detections it scores 47.11 HOTA against 47.32 for BoxMOT's ByteTrack. Close enough that the experiments after it mean something.

## First idea: run the detector less often

The obvious move is to run the detector on every Nth frame and let the tracker predict the frames in between.

| Detector runs on | Mean time per frame | HOTA |
|---|---:|---:|
| Every frame | 79.8 ms | 37.5 |
| Every 3rd frame | 26.7 ms | 36.0 |
| Every 5th frame | 16.1 ms | 33.0 |
| Every 10th frame | 8.1 ms | 28.9 |

Skipping two frames out of three cuts the mean time by 67% and costs 1.5 points. That is a good trade. Past that, accuracy falls quickly.

There is a catch in this table that the mean hides. The slowest frames did not get faster: the 99th percentile stayed near 80 ms at every interval. A frame that runs the detector costs what it always cost. A fixed interval improves your average and does nothing for your worst case.

## Second idea: watch the pixels between detector runs

Between detector runs, the tracker is guessing. It assumes each person keeps moving the way they were. I added optical flow, which follows small patches of the image from one frame to the next, and gave that motion to the tracker as a measurement.

![HOTA against mean frame time, with and without optical flow. The line with optical flow is higher, and the gap grows at long intervals.](/img/leantrack-interval.png)

It costs less than 2 ms a frame. The gain grows with the interval: 0.3 points at every 3rd frame, 3.2 points at every 10th, 6.7 points at every 20th. It also cut identity switches by a third to a half. With flow, detecting every 10th frame is almost as good as detecting every 5th frame without it.

## The real problem: a live stream

Everything above processes every frame and ignores the clock. So I simulated one. Frames arrive at the camera's rate, and an output only counts if it is ready before the next frame arrives.

I compared three loops:

- **Blocking.** Wait for the detector, then take the newest frame. Frames in between are dropped.
- **Background.** The detector runs in its own thread. Every frame gets an output from the tracker and optical flow. When a detector result arrives it is a few frames old, so optical flow moves those boxes forward to the current frame before the tracker uses them.
- **Background, no correction.** The same, but the stale boxes are used as they are.

| Loop | Mean output latency | HOTA |
|---|---:|---:|
| Blocking | 101.4 ms | 32.9 |
| Background | 5.1 ms | 34.5 |
| Background, no correction | 2.8 ms | 31.6 |

The background loop answers about 20 times sooner (101.4 / 5.1 = 19.9) **and** scores 1.6 points higher. It is faster and better, which does not happen often.

The third row is the part I would have got wrong without measuring. A detection that arrives three frames late describes where people were three frames ago. Use it as it is and the score drops 2.9 points, below even the blocking loop. Moving the late boxes forward with optical flow is what makes the background design work.

## Two results I did not expect

**The biggest model was not the best one.** Offline, the larger YOLOX-m beats YOLOX-s, 40.0 to 37.5. On the live stream, in the background loop, it loses: 33.0 to 34.5. Its results arrive five frames old instead of three, and a better answer about the distant past is worth less than a decent answer about the recent past.

**A faster model beat a smarter schedule.** I quantized YOLOX-s to 8-bit integers. That made it 2.8 times faster and cost 1.0 point offline. On the live stream it now fit inside one frame period, and a plain blocking loop with the quantized model scored 36.4, which is 1.9 points better than my careful background loop with the original model. All the scheduling work was worth less than making the detector fast enough to not need it.

## What did not work

These are in the repository, because they changed the design.

**Triggering the detector when the tracker looks unsure.** This seemed like the smart version of a fixed interval. I built two uncertainty signals, and they really do predict a bad box: when flow reliability was low, the box was wrong 78% of the time, against 16% when it was high. But running the detector at those moments did not fix the box. The trigger landed within half a point of a fixed interval, or below it. My guess is that low reliability often means the person is hidden, and a detector cannot see a hidden person either. I did not test that.

**Predicting which boxes are wrong.** A small model on eight features reached an AUC of 0.73. One of those features alone reached 0.71. And its probabilities were off on scenes with a moving camera, so filtering on them made the score worse.

**The background loop for a fast detector.** If the detector already fits in the frame period, moving it to the background just makes its answer one frame late. A blocking loop was 0.6 points better. I added a frame budget for this: wait for the detector only if it is expected to finish in time.

## One more thing: getting a lost person back

When someone walks behind a pole, the tracker loses them. When they come out, do they get their old identity back?

![Share of tracks that recover against the length of the gap, for four methods. The two appearance methods stay far above the two without appearance.](/img/leantrack-occlusion.png)

With position alone, 16% of tracks recovered after a 30-frame gap. Comparing appearance as well raised that to 57%. The surprise was how little was needed: a plain color histogram matched a neural re-identification network for gaps up to 30 frames, at a small fraction of the cost (0.07 ms a box against 1.6 ms). The network only pulled ahead on longer gaps.

And then the honest part: on the standard benchmark with strong detections, this changed the overall score by less than 0.1. The capability is real and the benchmark does not reward it.

## What I took from this

- **Do not wait for a slow detector.** Run it in the background and keep the tracks moving with optical flow.
- **Correct late results.** A stale detection used as fresh is worse than no background thread at all.
- **Make the model faster before you make the schedule smarter.** Quantization beat everything else I tried.
- **Choose the model for the stream, not for the leaderboard.** The best offline model was not the best live one.
- **Keep the results that failed.** Half of what I expected to work did not, and that is the more useful half.

## Limits

One laptop CPU, one run per configuration, no GPU and no small device. The live stream experiments use a simulated clock with measured timings, not a real camera. Changing the detector timing alone moves HOTA by about 0.7 on a live stream, so smaller differences between two live configurations are noise.

The code, every table, and eight short design records are in the [repository](https://github.com/yash-bitla/leantrack).
