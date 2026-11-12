[Home]({BASE}/) [Science]({BASE}/science) [Coast]({BASE}/coast) [Subscribe]({BASE}/subscribe)

# How Tidal Clocks Work

By [Mina Okafor]({BASE}/authors/mina-okafor)

A tide clock looks like a wall clock that lost a hand. It has **one pointer**, and that pointer ignores the sun completely: it follows the *moon*. One full turn takes 12 hours and 25 minutes, the average time between two high tides, as the [lunar day]({BASE}/glossary#lunar-day) is about 50 minutes longer than the solar one.

That single number is the whole trick. A quartz movement built for `44700` seconds per turn, instead of the usual 43200, keeps pace with the water for weeks. The [tide primer](https://tides.example.org/primer?station=4&view=%28full%29) from the harbor office explains why it drifts after that.

## Reading the dial

The dial is split in two halves. On the way down the left side the water is falling, on the way up the right side it is rising:

- Pointer at the top: **high tide**.
- Pointer at the bottom: low tide.
  - The numbers count the hours *until* the next turn of the tide.
  - Most dials print them from 5 down to 1.
- Halfway on either side: the current runs fastest.

## Setting one up

You only need a tide table and a little patience.

1. Look up today's high tide for your harbor.
2. Wait for that moment, ideally near a full or new moon.
   1. Put in a fresh battery.
   2. Turn the pointer to "High Tide".
3. Check it again after a month.

![A tide clock dial with one pointer near high tide]({BASE}/img/tide-clock-dial.png)

The dial of a brass tide clock. Photo: harbor archive.

### Why it drifts

The moon is not the only thing pulling. The sun adds its own, smaller tide, and the two fall in and out of step. A clock that assumes a fixed interval is right on average and wrong in detail:

| Moon phase | Tide type | Typical error |
| --- | --- | --- |
| New or full | Spring | under 10 min |
| First quarter | Neap | up to 60 min |
| Last quarter | Neap | up to 60 min |

> Set it on the spring tide and forgive it on the neap.
>
> An old chandler's rule

## Doing the sum yourself

The pointer position is one line of arithmetic. In JavaScript:

```js
const TIDE_MS = 12.42 * 60 * 60 * 1000;

function pointerAngle(now, lastHighTide) {
  const phase = ((now - lastHighTide) % TIDE_MS) / TIDE_MS;
  return phase * 360; // 0 = high tide, 180 = low tide
}
```

The same in Python, as the harbor office publishes it:

```python
TIDE_S = 44714

def pointer_angle(now, last_high_tide):
    return ((now - last_high_tide) % TIDE_S) / TIDE_S * 360
```

And the constant on its own, with no language given:

```
12 h 25 min 14 s
```

---

Tide clocks work best on coasts with two even tides a day, such as the Atlantic. Where the pattern is ~~simple~~ mixed, as on much of the Pacific coast, use a table. A [![Tide table for 2026]({BASE}/img/table-thumb.png)]({BASE}/downloads/tide-table-2026.pdf) is still the better tool there.

![Moonrise over the harbor wall]({BASE}/img/lazy-moonrise.jpg)

#### Related

- [Reading a barometer]({BASE}/coast/reading-a-barometer)
- [Five knots worth knowing]({BASE}/coast/knots)
- [The moon illusion]({BASE}/science/moon-illusion)

**Get the newsletter**

[About]({BASE}/about) [Privacy]({BASE}/privacy)Copyright 2026 The Harbor Review

We use one cookie to remember this banner.
