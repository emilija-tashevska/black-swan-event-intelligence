# Frontend — Black Swan Analytics Dashboard

Next.js App Router dashboard for exploring black swan events from Kalshi prediction markets.

## Development

```bash
npm install
npm run dev
```

Expects the backend API at `http://localhost:8000`.

## Static Build

For GitHub Pages deployment, build with:

```bash
NEXT_PUBLIC_STATIC=true NEXT_PUBLIC_BASE_PATH="/black-swan-event-intelligence" npm run build
```

In static mode, the app reads pre-exported JSON from `/data/` instead of calling the live API. Threshold values snap to pre-computed increments (5%, 10%, 15%, 20%, 25%).
