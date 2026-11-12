# Shadow parts

Some sites build their pages out of components that keep their content in a shadow tree, out of reach of a plain copy of the page. This page has four of them, and a clip has to contain what a reader sees in each.

```js
const high = 12.42;
const low = high / 2;
```

A note whose label comes from the component and whose text comes from the page:

**Note:** Slotted *light* text.

> Passed through two components, the inner one closed.

And a last paragraph of ordinary text, so that there is enough of it around the components for the page to read like an article with a beginning and an end.
