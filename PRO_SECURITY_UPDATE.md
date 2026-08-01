# Professional storefront and protected previews update

This package addresses the reported storefront, cart, preview, and browser-cache problems.

## Corrected

- Added a visible **Add image to cart** button to every matched photograph.
- Fixed the JavaScript cart failure caused by the missing `photoProducts` map.
- Added **Add all photos**, **Clear cart**, a live cart counter, and a sticky checkout bar.
- Portrait and landscape photographs now use `object-fit: contain`; the complete frame is visible and heads are not cropped.
- Preview images now receive a large central protection mark plus repeated Marin Fotografía y Video watermarks.
- Preview files are reduced-resolution only and are delivered with `Cache-Control: no-store`.
- Every search creates a random, 30-minute preview token. A photo preview cannot be opened without a valid token for that event.
- The final branded-image sample endpoint is administrator-only.
- Original high-resolution downloads remain behind an order whose payment status is confirmed.
- Replaced the old cache-first service worker. The new network-first service worker removes obsolete caches so deployments show the new design.
- Rebuilt the public site with a professional black, ivory, champagne-gold, and wine editorial design.

## Important limitation

A browser cannot completely prevent a visitor from taking a screenshot or saving anything that is visibly displayed. The practical protection is to show only a reduced, strongly watermarked preview and never expose the original file before payment. This package implements that model.

## Deploy

Upload the contents of this package to the root of the existing GitHub repository, preserving the `app` folder structure. After Render deploys, refresh the site once with `Ctrl + Shift + R` so the old service worker is replaced.
