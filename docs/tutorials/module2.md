# Module 2 Tutorial: The Enrollment State Machine

**One-line goal:** Only one file may change `Enrollment.status`, and it only allows moves from a fixed rulebook.

---

## 1. The story (teach this first)

Imagine a school. Every student must pass through **levels in order**, and a **strict gatekeeper** stands at the door of each level.

| School | Our system |
|---|---|
| A student | A lead |
| The student's journey through one school year | An **Enrollment** (one lead in one campaign) |
| The student's current level | `Enrollment.status` |
| The gatekeeper's rulebook | `ALLOWED` |
| The gatekeeper's diary | `Event` rows |
| The teacher who presses "Save" | The **caller** (commits the transaction) |

The gatekeeper:
1. Only lets a student move if the move is in his **rulebook**.
2. Says **"No!"** immediately to anything else.
3. Writes **one diary line** for every move he accepts.
4. Never presses "Save". The teacher does that.

---

## 2. The problem (30 seconds)

Without rules, any code can do:

```python
enrollment.status = "step2_sent"
```

Now we might email someone who **already replied**, who **said stop**, or whose address **bounced**.

In school terms: a student who already **left the school** suddenly shows up in Class 2 again. That should never happen.

---

## 3. The 13 levels (statuses)

```
new → scored → verified → drafted → queued → step1_sent → step2_sent → step3_sent → completed
```

**School version:** a student climbs Class 1 → 2 → 3 → ... → graduates.

Two special ways to leave early:

- **Expelled early** = `rejected`. Only possible in the early levels: `new`, `scored`, `verified`, `drafted`.
- **Student reacts** = `replied`, `bounced`, `unsubscribed`. Only possible once emailing starts: `queued`, `step1_sent`, `step2_sent`, `step3_sent`.

**Ending rooms (no exit door):** `completed`, `rejected`, `replied`, `bounced`, `unsubscribed`. Once a student enters, they stay.

---

## 4. The rulebook

```python
ACTIVE   = {"queued", "step1_sent", "step2_sent", "step3_sent"}
EXIT     = {"replied", "bounced", "unsubscribed"}
TERMINAL = EXIT | {"completed", "rejected"}

ALLOWED = {
    "new":        {"scored", "rejected"},
    "scored":     {"verified", "rejected"},
    "verified":   {"drafted", "rejected"},
    "drafted":    {"queued", "rejected"},
    "queued":     {"step1_sent"} | EXIT,
    "step1_sent": {"step2_sent", "completed"} | EXIT,
    "step2_sent": {"step3_sent", "completed"} | EXIT,
    "step3_sent": {"completed"} | EXIT,
}
```

**Read it like this:** "A student in `new` may only go to `scored` or `rejected`."

**Why are ending rooms not keys?**
They have no exit door, so `ALLOWED.get(status, set())` returns an empty set. The same happens for a typo like `"banana"`, so a bad status raises an error instead of slipping through.

---

## 5. The "No!" (the error)

```python
class IllegalTransition(Exception):
    def __init__(self, current, new):
        self.current, self.new = current, new
        super().__init__(f"cannot move enrollment from '{current}' to '{new}'")
```

**School version:** Ali already left school (`replied`). Someone tries to push him into Class 2 (`step2_sent`). The gatekeeper says:

> cannot move enrollment from 'replied' to 'step2_sent'

---

## 6. The gatekeeper function

```python
async def transition(db, enrollment, new_status, reason, payload=None):
    current = enrollment.status

    # 1. Check the rulebook BEFORE changing anything
    if new_status not in ALLOWED.get(current, set()):
        raise IllegalTransition(current, new_status)

    # 2. Move the student
    enrollment.status = new_status

    # 3. Ending room? Cancel the next appointment
    if new_status in TERMINAL:
        enrollment.next_send_at = None

    # 4. Write one diary line
    db.add(Event(
        enrollment_id=enrollment.id,
        type=f"status:{new_status}",
        payload={"reason": reason, **(payload or {})},
    ))
    # No commit. The teacher (caller) saves once at the end.
```

Adjust the `Event` import to match your models file.

**Why check first?** If the move is illegal, nothing changes and no diary line is written. It is as if nothing happened.

**Why no commit?** A job like `send_due` does several small tasks. One save at the end means **all or nothing**: if task 3 fails, tasks 1 and 2 are not half-saved.

---

## 7. Live demo (2 minutes)

```python
# e.status == "replied"
await transition(db, e, "step2_sent", "oops")
# IllegalTransition: cannot move enrollment from 'replied' to 'step2_sent'
```

Then show a legal move:

```python
# e.status == "queued"
await transition(db, e, "step1_sent", "email sent")
# e.status is now "step1_sent" and one Event row was added
```

---

## 8. The exam (tests, no database needed)

```python
class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)
```

The exam must check:

1. **All 26 allowed moves** succeed and set the new status.
2. **All 143 illegal moves** raise `IllegalTransition`, leave the status unchanged, and add **no** diary line.
3. An unknown level like `"banana"` raises.
4. Ending rooms clear `next_send_at`; normal moves keep it.
5. The diary line has the right `type` and contains `reason` plus any extra payload.
6. Rulebook sanity: every status is known, `ACTIVE` and `TERMINAL` do not overlap, and every status is either a key in `ALLOWED` or terminal.

**Tip:** loop over all 13 x 13 pairs instead of writing 169 tests by hand. Allowed pairs must pass, the rest must raise.

Run from `backend/`:

```
venv\Scripts\python.exe -m pytest -q
```

---

## 9. Recap (say this at the end)

| Idea | School version | Why |
|---|---|---|
| Plain strings, no Enum | Levels are just names on a board | The rulebook is the validator |
| Validate before mutating | Check the rulebook before the student moves | A failed move leaves no trace |
| One event per move | One diary line per accepted move | Full history |
| Caller commits | Teacher presses "Save" once | Atomic jobs |
| Only `transition()` writes status | Only the gatekeeper moves students | No sneaky bugs |

---

## Homework for viewers

Add a new status `paused` and run the tests. Which test fails? That is exactly why the sanity tests exist: they catch a forgotten status.