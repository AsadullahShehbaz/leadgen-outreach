# Module 3 Tutorial: The Gate Clock and the Pass Counter

**Goal:** before any email goes out, answer two questions: *Is the gate open?* and *Are there passes left today?*

**School analogy:**
- The school is the **workspace**.
- Each classroom is a **mailbox**.
- Each student leaving is one **email**.
- The teacher lets a student out only if the gate is open **and** the classroom still has passes.

## 1. The gate clock (`windows.py`)

The gate is open **Mon-Fri, 9:00-17:00** in the workspace's local time.

```python
window = SendWindow(start_hour=9, end_hour=17, weekdays={1,2,3,4,5})  # 1=Mon

in_send_window(now, "Asia/Karachi", window)   # True or False
next_window(now, "Asia/Karachi", window)      # next opening, in UTC
workspace_day(now, "Asia/Karachi")            # local date, used for the cap key
```

Example: it is Friday 6 PM, `in_send_window` says `False`, and `next_window` says Monday 9 AM.

Three rules keep it safe:
1. `now` must have a timezone. A naive time raises `ValueError`.
2. An unknown timezone raises an error. It never falls back to UTC.
3. Daylight saving is handled by `ZoneInfo`, so you write no offset math. This is why `tzdata` is in `requirements.txt`, since Windows and Docker don't ship the timezone data.

## 2. The pass counter (`limiter.py`)

Each mailbox gets N passes per local day, counted in Redis.

```
key = cap:<mailbox_id>:20261121     # new date = new counter
```

```python
async def try_acquire(redis, mailbox_id, cap, day):
    if cap <= 0:
        return False                  # no passes at all
    n = await redis.incr(key)         # take a pass
    if n == 1:
        await redis.expire(key, 30h)  # first pass of the day: start the cleanup timer
    if n > cap:
        await redis.decr(key)         # too many, put it back
        return False
    return True
```

**Why `INCR` first, then check?** `INCR` is atomic, so Redis does it as one indivisible step. If 200 students rush the door at once, each gets a different number. If you read the count, checked it, and then wrote it, two students could both read "9" and both get out.

**`release()`** gives a pass back when a send fails temporarily. Call it exactly once per acquire. A double release means the classroom effectively has 11 passes.

## 3. Config (`.env`)

```
SEND_WINDOW_START_HOUR=9
SEND_WINDOW_END_HOUR=17
SEND_WINDOW_DAYS=1,2,3,4,5     # 1=Monday ... 7=Sunday
```

A typo like `1,2,x` fails loudly, because a garbled notice on the door is better than the teacher guessing.

## 4. The tests, with no database needed

- **Windows:** just before the start, exactly at the start, mid-window, exactly at the end, a weekend, UTC vs Karachi, and a New York daylight saving case.
- **Limiter:** exactly `cap` sends succeed and the next one fails. Mailboxes and days are independent. `cap <= 0` never creates a key.
- **The big test:** 200 concurrent acquires with cap 10 must give exactly 10 `True`. A `FakeRedis` (dict plus a lock) makes this run without a server.

Run from `backend/`:

```
venv\Scripts\python.exe -m pytest -q
```

## 5. Recap

| Piece | School version | Why |
|---|---|---|
| Send window | Gate is open 9-5 on weekdays | Don't email at 3 AM on Sunday |
| Workspace timezone | The school's own clock | "9 AM" must mean the client's 9 AM |
| Redis `INCR` | Teacher hands out numbered passes | Atomic, so nobody gets a duplicate number |
| Cap key with date | Fresh tally sheet each day | Resets at the client's midnight |
| 30h TTL | Old sheets get thrown away | Redis doesn't fill up |
| `release()` once | Return a pass only once | Prevents extra sends |
| Fail loudly | Broken clock means the gate stays shut | Never send by guessing |

**Homework for viewers:** set `cap=3` and fire 10 acquires at once. How many get `True`? Then call `release()` twice for one pass and see what breaks.

I can save this as `docs/tutorials/module3.md` if you want it in your repo.