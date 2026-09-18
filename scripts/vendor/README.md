# Vendored, on purpose

React 18.3.1 (UMD), ReactDOM 18.3.1 (UMD), htm 3.1.1. 144 KB total.

They are committed rather than fetched from a CDN so the builder needs **no internet and no
build step** - no npm, no bundler, no node. `htm` gives JSX-like syntax in tagged template
literals, which is why there is no Babel here either.

A CDN would have been fewer files and one more thing to be down or blocked on a work laptop.
