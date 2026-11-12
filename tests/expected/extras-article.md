# Edge cases

Special characters: 2 \* 3 = 6, snake\_case\_name, a \[bracket\] and a back\`tick.

\# not a heading

1\. not a list

\- not a bullet

Line one  
line two

Non breaking space and a zerowidth space.

## Links

<https://example.com/> is an autolink, [mail](mailto:hi@example.com) is kept, script links lose their target, [same-page]({BASE}/extras.html#top) links become absolute, and [odd paths]({BASE}/path%20with%20spaces/%281%29.html) are encoded.

### [Card title]({BASE}/cards/1)

Card text under the title.

## Lists

- First
  - Wrongly nested child
- Second

  with a paragraph

- [x] Done task
- [ ] Open task

5. Five
6. Six

## Tables

|  |  |
| --- | --- |
| Port | 22 |
| Protocol | a \| b |

Opening hours

| Day | Open | Close |
| --- | --- | --- |
| Mon | Closed |  |
| Tue, Wed | 9:00 | 17:00 |
|  | 10:00<br>(late start) | 16:00 |

Left column text.

Right column text.

Only one cell

| A | B |
| --- | --- |
| 1 | 2 |

## Code

````html
<p>Hello</p>
```
fenced inside
```
````

```
line one
line two
```

```
x = 1
y = 2
```

```ruby
puts 1
```

```css
a { color: teal; }
```

Inline ``a `tick` inside`` code.

## Other blocks

### Wiki style

**Term**

Its definition.

**More detail**

Hidden until opened.

[Tide clock demo](https://www.youtube.com/embed/abc123)

![A \[bracketed\] alt]({BASE}/pic%20one.png)

Text with "inline quote" and marked words.

## Hidden

Class hidden text.

Shown through display contents.
