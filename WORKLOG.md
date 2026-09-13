# Work log

My notes for each day: what I was thinking, what I tried, and what didn't work.

---

## Day 1 — Understanding the data, and Step 1

### Morning: I decided not to write any code for the segmenter yet

My first instinct was to jump straight into something like change-point detection or
clustering the events. I stopped myself, because of one line in the brief: dataset B has
different departments and different applications. If I built something on dataset A
without checking what actually carries over, I could end up with a method that scores
great on A and produces nothing on B. So I spent the first part of the day just measuring.

That turned out to be the right call, and here is why.

**The portal is the key.** All three business systems are the same web app served on
three different local ports (A uses 5122/5123/5124, B uses 5132/5133/5134), and each one
has the same five screens. When I cross-checked `(port, screen)` against dataset A's
ground truth, it lined up 1:1 with the 15 process codes. So the process identity is
basically written in the URL — I don't have to infer it.

**But the case IDs don't carry over.** In dataset A the table rows have the case ID inside
the HTML id, like `#la-row-SUP-181750-001`. I got excited about this because it would make
segmentation trivial. Then I checked dataset B: the rows are just
`tr:nth-of-type(4)` — position only, zero case IDs in the whole dataset. A's buttons are
also named things like `-confirm` and `-approve`, while B collapsed everything to `-ok`.

If I had skipped this check I would have built the whole thing on case IDs and only found
out at the very end. This is the moment that justified the whole morning.

**Some data problems I hit while poking around:**

- `context.active_app` lies. It's stale about 38% of the time on app switches — it tells
  you the app you just left, not the one you're in. I trusted it at first and got weird
  results (Excel's Ctrl+F showing up as Chrome, 1,293 times). Had to rebuild the "current
  app" from the app_switch payload instead.
- 88% of app_switch events are switches from an app to *itself*. So you can't use the
  count of app switches as a measure of task switching.
- Events are not in timestamp order in the files. I sort everything now.
- Clipboard text and form input values are 100% null (redacted). I spent a while looking
  for the text before accepting it just isn't there.
- 7 of A's 63 sessions have no browser extension data at all. This became my main problem
  for the rest of the day.

### Ground truth needed fixing before I could use it

`gt_manifest.json` has `end_ts: null` on 257 of the 2,009 executions — that's 12.8% of my
reference data missing. I didn't want to just throw those away, so I rebuilt the intervals
from the `gt.jsonl` event stream instead.

While doing this I figured out something that had confused me. The schema doc warns that
`process_started` sometimes appears twice in a row and calls it a quirk. But 1,819 starts
minus 1,590 switch-outs = 229, and there are 230 duplicates. They match. So a "duplicate
start" isn't a bug at all — it's just how the log records doing the same process twice in
a row. Good thing I checked, because I almost wrote code to delete them.

My rebuilt version matches all 1,752 intervals the manifest does give, to the millisecond,
and recovers the 257 missing ones.

### Afternoon: building the segmenter

The idea I settled on is simple enough to explain in one sentence: **each case starts when
the worker clicks a row in the worklist and ends when they click the action button, and
everything in between (Excel, Word, Notepad) belongs to that case.**

Getting there took a few wrong turns.

**Wrong turn 1: I blamed my method for a bad metric.** My first boundary F1 was 0.527 and
I assumed the method was just mediocre. It wasn't. The ground truth writes
"switched out of A" and "started B" about 3 milliseconds apart, so it looks like two
boundaries when it's really one handover. Any method that emits one boundary per switch
is capped around 0.56 recall no matter how good it is. Once I merged those pairs in the
scoring code, the same segmenter scored 0.825. I was measuring the file format, not my
work.

**Wrong turn 2: I assumed the gap between two cases gets split down the middle.** It
doesn't. I measured it and found that 1,844 out of 1,946 consecutive executions in the
ground truth touch each other almost exactly — there is basically no gap. And the long
pauses aren't *between* cases, they're *inside* them, after the button click. So the rule
should be: a small margin before the row click, and then the case keeps the dead time
after it until the next one starts. That change alone took mean IoU from 0.76 to 0.80.

**Wrong turn 3 (the big one): the sessions with no browser extension.** For those 7
sessions I tried counting round trips (portal → Excel → portal) as cases. It recovered
11.6% of them. Basically useless, so I deleted it.

Then I looked closer and realised the actual problem was worse than I thought: when the
extension is missing you don't just lose the clicks, you lose the browser URL too. So my
context resolution was at literally 0% for those sessions and they produced **zero**
segments. That's 11% of dataset A and 1 session in dataset B.

The fix took me a while but I like it. The window title still tells you which system
(`財務会計システム` etc.), and about 4% of events have OCR text containing the page
breadcrumb (`ダッシュボード / 発注管理`) which tells you the screen. I learn the
"screen name → screen" mapping automatically from the sessions where both the URL and the
breadcrumb are visible, then apply it where the URL is gone. Nice side effect: the same
mechanism is what discovers dataset B's process names, so one thing solved two problems.

**Wrong turn 4: my replacement fallback only worked on A.** For the extension-less
sessions I found that the row click still shows up as a plain mouse click with the browser
in front. Rule: take the last browser click before the worker leaves the browser. Works on
A (fires once per case 74% of the time). Then I ran it on B's extension-less session and
got 19 segments when similar sessions have ~45.

The reason is that A and B just work differently. In A the worker leaves the browser
constantly to check Excel. In B they mostly stay in the browser. So I had to add a second
rule (the click right after pasting into the note field) and pick between the two per
session, based on how often that session leaves the browser. I tried just using both rules
together first, but that double-counts 58 of A's cases. The threshold I use has a fairly
narrow margin (A sessions measure 0.96–2.21, B measures 0.43), so I wrote it down as an
assumption rather than pretending it's solid.

**Two silly bugs** that I only caught because a number looked impossible: my coverage
metric reported 143% (broken interval union), and at one point every segment in the
sessions I had *just fixed* disappeared, because a divide-by-something-tiny made all the
margins zero.

### Things I decided not to do

- **No machine learning.** Not because it's bad, but because the simple thing already gets
  ARI 0.993 against the ground truth labels. Anything learned would have to beat that and
  would be much harder to explain to a client.
- **No classifier trained on A's process names.** B has different processes, so it would
  be useless there.
- **I stopped tuning the boundaries.** I checked what a perfect method could do: even if
  you place every boundary at the exactly correct average offset, you only get 67% within
  1 second, because the click itself varies by about ±0.8s. So chasing 1-second accuracy
  is just fitting noise. I said so in the report instead of hiding it.
- **One improvement I skipped on purpose:** I could learn the nav menu click coordinates
  to recover the screen better in extension-less sessions. It would help, but it affects
  1 session out of 15 in B — maybe 2% of the output. Not worth a day-1 afternoon.

### Two things I couldn't solve

**The biggest one:** dataset B's busiest screen (`hr_expense_and_pay_change`, 134
segments) is actually hosting *two* different processes — expense claims (`P1-...`) and
salary changes (`P4-...`) are mixed in the same worklist. I can see this in the OCR text.
But the code that would tell me which is which only appears in 5 of my 684 segments, and
B's rows are positional so there's no way to join them. I left it as one label and wrote
it up as my main known defect. I'd rather say "I couldn't separate these" than guess.

**Something I chose to ignore:** my merge test says two obviously different processes
(HR expense handling and Ops inventory) are 99% similar. They're not — that's just because
every screen in this portal is used the same way (click row, paste, press OK). The metric
was measuring UI style, not business purpose. So I ignored it and explained why. It felt
strange to override my own analysis, but following it would have been clearly wrong.

### Where the day went

Roughly: 40% measuring the data before writing anything, 35% building and rebuilding the
segmenter, 15% just on the no-extension sessions, 10% on validation and writing up.

The 40% at the start felt slow at the time but it's what found the port/screen structure
and caught the case-ID trap.

### How I used AI

I used Claude Code (Opus 5) throughout the day, mostly as a way to ask the data questions
quickly. When I wondered "who owns the gap between two cases?", I could turn that into an
actual measurement in a couple of minutes instead of just assuming an answer. It also
wrote most of the scripts to my direction, and helped me read the Japanese screen text and
window titles to work out what the business processes actually are.

Two things I was careful about. First, every number in my report comes from a script in
`src/` that can be re-run — not from the model's memory. Second, it was wrong a few times
(the round-trip fallback, the boundary metric), and what caught it every time was the
measurement, not me reading the reasoning and spotting the flaw. So I tried to check
things by running them rather than by nodding along.

### Result and what's next

684 segments across all 15 dataset-B sessions, 12 processes. On dataset A: boundary F1
0.858 at 2 seconds, mean IoU 0.865, and the 15 process labels come out matching the ground
truth codes almost perfectly (ARI 0.912). I held out 21 sessions from tuning and they
scored *better* than the 42 I tuned on, so I don't think I've overfitted.

Tomorrow: Step 2. Process frequencies, cycle times, how many people do each one, and then
a prioritised list of automation candidates. Before that I want to have one more attempt
at the P1/P4 split, because it's the biggest label and the ROI ranking will depend on it.
